# -*- coding: utf-8 -*-
""" Watches the JK2 CTF YouTube channel and announces new uploads to a
	per-guild configured channel. Off by default (=set_youtube_enabled on).

	Uses YouTube's public Atom feed (no API key, no quota) instead of the
	YouTube Data API — one plain GET, well within what a hobby bot should need
	for "is there a new video yet". Polls from the think loop, same pattern as
	jk2_servers.py. """

import re
import asyncio
import xml.etree.ElementTree as ET

import aiohttp
from nextcord import DiscordException

from core.client import dc
from core.database import db
from core.console import log

CHANNEL_ID = "UCeyBUO4DiHBxuW6xPgDiHGQ"  # Jedi Knight 2 CTF — youtube.com/@jk2ctf
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
POLL_INTERVAL = 10 * 60
TIMEOUT = aiohttp.ClientTimeout(total=10)

NS = {
	'atom': 'http://www.w3.org/2005/Atom',
	'yt': 'http://www.youtube.com/xml/schemas/2015',
	'media': 'http://search.yahoo.com/mrss/',
}
# Video descriptions on this channel include a line like "In this demo: sora, ewok, shax".
DEMO_PLAYERS_RE = re.compile(r"^In this demo:\s*(.+)$", re.MULTILINE)

db.ensure_table(dict(
	tname="guild_youtube",
	columns=[
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="enabled", ctype=db.types.bool, default=0, notnull=True),
		dict(cname="last_video_id", ctype=db.types.str),
	],
	primary_keys=["guild_id"]
))

_next_poll_at = 0
_poll_task = None


async def get_cfg(guild_id):
	return await db.select_one(
		['channel_id', 'enabled', 'last_video_id'], 'guild_youtube', where=dict(guild_id=guild_id)
	)


async def _upsert(guild_id, **fields):
	if await get_cfg(guild_id) is None:
		await db.insert('guild_youtube', dict(guild_id=guild_id, **fields))
	else:
		await db.update('guild_youtube', fields, keys=dict(guild_id=guild_id))


async def set_channel(guild_id, channel_id):
	await _upsert(guild_id, channel_id=channel_id)


async def set_enabled(guild_id, enabled):
	await _upsert(guild_id, enabled=int(enabled))


def _parse_entry(entry):
	video_id = entry.findtext('yt:videoId', default='', namespaces=NS)
	title = entry.findtext('atom:title', default='', namespaces=NS)
	link_el = entry.find('atom:link', NS)
	url = (link_el.get('href') if link_el is not None else None) or f"https://www.youtube.com/watch?v={video_id}"

	description = ""
	if (group := entry.find('media:group', NS)) is not None:
		description = group.findtext('media:description', default='', namespaces=NS) or ""
	players_match = DEMO_PLAYERS_RE.search(description)

	return dict(
		video_id=video_id, title=title, url=url,
		players=players_match.group(1).strip() if players_match else None
	)


async def fetch_latest():
	""" Newest-first list of recent uploads (the feed's own order), or [] on
		any fetch/parse failure — callers treat that as "nothing to do", not
		an error, since a poll cycle just tries again later. """
	try:
		async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
			async with session.get(FEED_URL) as resp:
				if resp.status != 200:
					return []
				xml_text = await resp.text()
	except (aiohttp.ClientError, asyncio.TimeoutError):
		return []

	try:
		root = ET.fromstring(xml_text)
		return [_parse_entry(e) for e in root.findall('atom:entry', NS)]
	except ET.ParseError:
		return []


async def think(frame_time):
	global _next_poll_at, _poll_task
	if frame_time < _next_poll_at:
		return
	_next_poll_at = frame_time + POLL_INTERVAL
	if _poll_task and not _poll_task.done():
		return  # previous poll still running
	_poll_task = asyncio.get_event_loop().create_task(_poll())


async def _poll():
	try:
		configs = [c for c in await db.select(
			['guild_id', 'channel_id', 'enabled', 'last_video_id'], 'guild_youtube'
		) if c['enabled'] and c['channel_id']]
		if not configs:
			return

		videos = await fetch_latest()
		if not videos:
			return
		ids = [v['video_id'] for v in videos]

		for cfg in configs:
			channel = dc.get_channel(cfg['channel_id'])
			if channel is None:
				continue

			if not cfg['last_video_id']:
				# First poll since being enabled — baseline to "now" instead of
				# announcing the entire existing back-catalogue as if it's new.
				await db.update('guild_youtube', dict(last_video_id=videos[0]['video_id']), keys=dict(guild_id=cfg['guild_id']))
				continue

			if cfg['last_video_id'] in ids:
				new_videos = videos[:ids.index(cfg['last_video_id'])]
			else:
				# Last-seen video fell off the feed (more uploads than the feed
				# holds since our last poll) — post just the newest rather than
				# guess how many were actually missed.
				new_videos = videos[:1]
			if not new_videos:
				continue

			for video in reversed(new_videos):  # oldest of the new batch first
				text = f"📺 New JK2 CTF upload: **{video['title']}**"
				if video['players']:
					text += f"\n👥 In this demo: {video['players']}"
				text += f"\n{video['url']}"
				try:
					await channel.send(text)
				except DiscordException as e:
					log.error(f"YouTube watch: failed to post in #{channel.name}: {e}")

			await db.update('guild_youtube', dict(last_video_id=new_videos[0]['video_id']), keys=dict(guild_id=cfg['guild_id']))
			log.info(f"YouTube watch: posted {len(new_videos)} new upload(s) in guild {cfg['guild_id']}.")
	except Exception as e:
		import traceback
		log.error(f"YouTube poll failed: {str(e)}\n{traceback.format_exc()}")
