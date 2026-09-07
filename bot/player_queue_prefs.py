# -*- coding: utf-8 -*-
""" Per-player channel linking. Lets a player link two or more queue channels
	(e.g. #comp and #casual) so a bare =j / ++ (no queue names given) in one
	also joins them in the others, and a bare =l / -- in one also leaves the
	others -- instead of only ever touching the channel the command was typed
	in. Off by default: with nothing set, =j/=l behave exactly as they always
	have (bot/commands/queues.py checks get_linked_channels and no-ops when
	it's empty).

	One flat group per player (not per-channel-pair): channel ids are globally
	unique on Discord, so a single row is enough to cover however many
	channels a player links together. """

from core.database import db

db.ensure_table(dict(
	tname="player_linked_channels",
	columns=[
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="channels", ctype=db.types.str),  # comma-separated channel ids
	],
	primary_keys=["user_id"]
))


async def get_linked_channels(user_id):
	""" Returns a list of int channel ids this player has linked (their own
		channel included), or an empty list if they haven't linked anything. """
	row = await db.select_one(['channels'], 'player_linked_channels', where=dict(user_id=user_id))
	if not row or not row['channels']:
		return []
	return [int(c) for c in row['channels'].split(",") if c]


async def add_linked_channels(user_id, channel_ids):
	""" Adds channel_ids to the player's existing group (union, not replace). """
	current = set(await get_linked_channels(user_id))
	current.update(channel_ids)
	await _save(user_id, current)


async def clear_linked_channels(user_id):
	await _save(user_id, set())


async def _save(user_id, channel_ids):
	value = ",".join(str(c) for c in sorted(channel_ids))
	if await db.select_one(['user_id'], 'player_linked_channels', where=dict(user_id=user_id)) is None:
		await db.insert('player_linked_channels', dict(user_id=user_id, channels=value))
	else:
		await db.update('player_linked_channels', dict(channels=value), keys=dict(user_id=user_id))
