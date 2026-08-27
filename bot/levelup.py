# -*- coding: utf-8 -*-
""" Pings a player when Soracle records a tier change (from the auto-calibrator
	or an admin edit) or a new equipped title. Off by default (=set_levelup_enabled
	on). Both events poll independently and a player who gets both in the same
	cycle is announced once, combined -- the two changelogs advance separate
	cursors, so one endpoint 500ing (e.g. title-changelog before its migration
	has run) never blocks the other. Polls from the think loop, same pattern as
	jk2_servers.py/youtube.py. """

import asyncio

from nextcord import DiscordException

from bot import soracle
from core.client import dc
from core.database import db
from core.console import log

POLL_INTERVAL = 15 * 60

db.ensure_table(dict(
	tname="guild_levelup",
	columns=[
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="enabled", ctype=db.types.bool, default=0, notnull=True),
		dict(cname="tier_since", ctype=db.types.str),
		dict(cname="title_since", ctype=db.types.str),
	],
	primary_keys=["guild_id"]
))

_next_poll_at = 0
_poll_task = None


async def get_cfg(guild_id):
	return await db.select_one(
		['channel_id', 'enabled', 'tier_since', 'title_since'], 'guild_levelup', where=dict(guild_id=guild_id)
	)


async def _upsert(guild_id, **fields):
	if await get_cfg(guild_id) is None:
		await db.insert('guild_levelup', dict(guild_id=guild_id, **fields))
	else:
		await db.update('guild_levelup', fields, keys=dict(guild_id=guild_id))


async def set_channel(guild_id, channel_id):
	await _upsert(guild_id, channel_id=channel_id)


async def set_enabled(guild_id, enabled):
	await _upsert(guild_id, enabled=int(enabled))


def _who(name, discord_id):
	return f"<@{discord_id}>" if discord_id else f"**{name}**"


def _build_message(entry):
	parts = []
	tier_dropped = False
	if 'tier' in entry:
		old, new = entry['tier']
		tier_dropped = new < old
		parts.append(f"moved from Tier {old} to Tier {new}")
	if 'title' in entry:
		old_title, new_title, rarity = entry['title']
		bit = f"earned their first title: **{new_title}**" if old_title is None else f"title upgraded to **{new_title}**"
		if rarity:
			bit += f" ({rarity})"
		parts.append(bit)

	# A bare tier drop isn't something to celebrate -- only skip the party icon
	# when there's no title change to offset it (a title is always a gain,
	# since _merge_title_changes already filters out unequips).
	celebratory = 'title' in entry or not tier_dropped
	icon = "🎉" if celebratory else "📉"
	punctuation = "!" if celebratory else "."
	return f"{icon} {_who(entry['name'], entry['discord_id'])} " + " and ".join(parts) + punctuation


async def think(frame_time):
	global _next_poll_at, _poll_task
	if frame_time < _next_poll_at:
		return
	_next_poll_at = frame_time + POLL_INTERVAL
	if _poll_task and not _poll_task.done():
		return  # previous poll still running
	_poll_task = asyncio.get_event_loop().create_task(_poll())


async def _merge_tier_changes(combined, cfg):
	""" Fetches tier changes since the stored cursor, folds announceable ones into
		`combined`, and returns the new cursor value (or the old one on failure /
		no new rows). The very first poll (no stored cursor) baselines silently --
		Soracle has ~100 rows of real history, and announcing all of it the moment
		someone flips the feature on would be pure backlog spam. """
	try:
		data = await soracle.fetch_tier_changelog(cfg['tier_since'])
	except soracle.SoracleError as e:
		log.error(f"Level-up poll: tier-changelog fetch failed: {e}")
		return cfg['tier_since']

	changes = data.get('changes') or []
	if not changes:
		return cfg['tier_since']

	if cfg['tier_since']:
		for c in changes:
			key = c.get('discordId') or c['name']
			combined.setdefault(key, dict(name=c['name'], discord_id=c.get('discordId')))['tier'] = (
				c['oldTier'], c['newTier']
			)
	return changes[-1]['at']  # oldest-first order -> last entry is newest


async def _merge_title_changes(combined, cfg):
	""" Same shape as _merge_tier_changes. An unequip (newTitle None) is skipped --
		not an achievement, not ping-worthy -- but its `at` still advances the
		cursor so it isn't refetched forever. """
	try:
		data = await soracle.fetch_title_changelog(cfg['title_since'])
	except soracle.SoracleError as e:
		log.error(f"Level-up poll: title-changelog fetch failed: {e}")
		return cfg['title_since']

	changes = data.get('changes') or []
	if not changes:
		return cfg['title_since']

	if cfg['title_since']:
		for c in changes:
			if not c.get('newTitle'):
				continue
			key = c.get('discordId') or c['name']
			combined.setdefault(key, dict(name=c['name'], discord_id=c.get('discordId')))['title'] = (
				c.get('oldTitle'), c['newTitle'], c.get('rarity')
			)
	return changes[-1]['at']


async def _poll():
	try:
		configs = [c for c in await db.select(
			['guild_id', 'channel_id', 'enabled', 'tier_since', 'title_since'], 'guild_levelup'
		) if c['enabled'] and c['channel_id']]
		if not configs:
			return

		for cfg in configs:
			channel = dc.get_channel(cfg['channel_id'])
			if channel is None:
				continue

			combined = {}
			tier_since = await _merge_tier_changes(combined, cfg)
			title_since = await _merge_title_changes(combined, cfg)

			for entry in combined.values():
				try:
					await channel.send(_build_message(entry))
				except DiscordException as e:
					log.error(f"Level-up poll: failed to post in #{channel.name}: {e}")

			if tier_since != cfg['tier_since'] or title_since != cfg['title_since']:
				await db.update(
					'guild_levelup', dict(tier_since=tier_since, title_since=title_since),
					keys=dict(guild_id=cfg['guild_id'])
				)
			if combined:
				log.info(f"Level-up poll: announced {len(combined)} change(s) in guild {cfg['guild_id']}.")
	except Exception as e:
		import traceback
		log.error(f"Level-up poll failed: {str(e)}\n{traceback.format_exc()}")
