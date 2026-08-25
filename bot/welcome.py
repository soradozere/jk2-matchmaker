# -*- coding: utf-8 -*-
""" Per-guild welcome/leave announcements — replaces MEE6's greeter. Posting is
	off until an admin sets a channel with =set_welcome_channel; the message text
	itself is editable with =set_welcome_message / =set_leave_message and falls
	back to the defaults below until then. Powers on_member_join/on_member_remove
	in bot/events.py. """

import string
from datetime import datetime, timezone

from nextcord import DiscordException

from core.database import db
from core.console import log
from core.utils import get_nick

import bot

DEFAULT_WELCOME_MESSAGE = (
	"👋 Hey {member}! Welcome to **{guild}**!\n\n"
	"Join a queue with `=j` / `++`, or `=help` for the full command list.\n"
	"Download the NWH client and check stats at: {site}"
)
DEFAULT_LEAVE_MESSAGE = "👋 **{name}** left after `{duration}` in the server."

db.ensure_table(dict(
	tname="guild_welcome",
	columns=[
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="welcome_message", ctype=db.types.text),
		dict(cname="leave_message", ctype=db.types.text),
	],
	primary_keys=["guild_id"]
))


class _SafeDict(dict):
	""" Lets a stored template reference an unknown {placeholder} without crashing —
		it's left in the output as-is instead of raising KeyError. """
	def __missing__(self, key):
		return "{" + key + "}"


def _safe_format(template, **kwargs):
	return string.Formatter().vformat(template, (), _SafeDict(**kwargs))


def _humanize_duration(seconds):
	""" 'time in server' for the leave message, in plain words instead of a
		H:MM:SS timer. Sub-day durations show two units (hours+minutes,
		minutes+seconds) since the precision is meaningful there — a same-day
		leave is worth distinguishing from a week-long stay. Day-scale and up
		collapses to a single unit (days, or years once you're over a year) —
		nobody needs hour-level precision for a months-old member. """
	def unit(n, name):
		return f"{n} {name}{'s' if n != 1 else ''}"

	seconds = int(seconds)
	if seconds < 60:
		return unit(seconds, "second")
	if seconds < 3600:
		m, s = divmod(seconds, 60)
		return " ".join(filter(None, [unit(m, "minute"), unit(s, "second") if s else None]))
	if seconds < 86400:
		h, rem = divmod(seconds, 3600)
		m = rem // 60
		return " ".join(filter(None, [unit(h, "hour"), unit(m, "minute") if m else None]))

	days = seconds // 86400
	if days < 365:
		return unit(days, "day")
	years, rem_days = divmod(days, 365)
	months = rem_days // 30
	return " ".join(filter(None, [unit(years, "year"), unit(months, "month") if months else None]))


async def get_cfg(guild_id):
	return await db.select_one(
		['channel_id', 'welcome_message', 'leave_message'], 'guild_welcome', where=dict(guild_id=guild_id)
	)


async def _upsert(guild_id, **fields):
	if await get_cfg(guild_id) is None:
		await db.insert('guild_welcome', dict(guild_id=guild_id, **fields))
	else:
		await db.update('guild_welcome', fields, keys=dict(guild_id=guild_id))


async def set_channel(guild_id, channel_id):
	await _upsert(guild_id, channel_id=channel_id)


async def set_welcome_message(guild_id, message):
	await _upsert(guild_id, welcome_message=message)


async def set_leave_message(guild_id, message):
	await _upsert(guild_id, leave_message=message)


async def _post(guild, channel_id, text):
	if not channel_id or (channel := guild.get_channel(channel_id)) is None:
		return
	try:
		# suppress_embeds: a plain link in the message (e.g. the site URL) would
		# otherwise get Discord's auto-unfurled preview card under every message.
		await channel.send(text, suppress_embeds=True)
	except DiscordException as e:
		log.error(f"Could not post welcome/leave message in guild {guild.id}: {e}")


async def on_join(member):
	cfg = await get_cfg(member.guild.id)
	if not cfg:
		return
	text = _safe_format(
		cfg['welcome_message'] or DEFAULT_WELCOME_MESSAGE,
		member=member.mention, guild=member.guild.name, site=bot.soracle.site_url()
	)
	await _post(member.guild, cfg['channel_id'], text)


async def on_leave(member):
	cfg = await get_cfg(member.guild.id)
	if not cfg:
		return
	if member.joined_at:
		duration = _humanize_duration((datetime.now(timezone.utc) - member.joined_at).total_seconds())
	else:
		duration = "an unknown amount of time"
	text = _safe_format(
		cfg['leave_message'] or DEFAULT_LEAVE_MESSAGE,
		name=get_nick(member), guild=member.guild.name, duration=duration
	)
	await _post(member.guild, cfg['channel_id'], text)
