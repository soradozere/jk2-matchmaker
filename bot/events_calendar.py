# -*- coding: utf-8 -*-
""" Bot-wide scheduled events (a planned manhunt, a CTF pub night, ...).

	Mods/admins add an event with a name and a start time; it is announced with
	@everyone in every channel the bot is enabled in. Players opt in per event
	(=event_sub) and get one DM an hour before it starts. Events are not tied to a
	guild, and live in the database so a redeploy can't lose them or re-send a reminder.

	Times are entered as UK time (handles BST/GMT) or as a Discord <t:...> timestamp,
	and stored as a unix timestamp. """

import re
import asyncio
import traceback
from datetime import datetime, timedelta
from time import time
from zoneinfo import ZoneInfo

from nextcord import Embed, Colour, DiscordException

import bot
from core.client import dc
from core.database import db
from core.console import log

INPUT_TZ = ZoneInfo("Europe/London")
REMIND_BEFORE = 60 * 60  # DM subscribers this long before the start
KEEP_AFTER_START = 3 * 60 * 60  # events vanish from =events this long after they start
CHECK_INTERVAL = 60
DM_SPACING = 0.5  # seconds between DMs, to stay clear of Discord's rate limits
DATE_CHOICES = 30  # days offered by the /event_add date autocomplete (Discord caps choices at 25)
MAX_NAME = 100
MAX_NOTE = 500

TIMESTAMP_RE = re.compile(r"^<t:(\d{1,12})(?::[a-zA-Z])?>$")
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

db.ensure_table(dict(
	tname="bot_events",
	columns=[
		dict(cname="event_id", ctype=db.types.int, autoincrement=True),
		dict(cname="name", ctype=db.types.str),
		dict(cname="note", ctype=db.types.text),
		dict(cname="starts_at", ctype=db.types.int),
		dict(cname="created_by", ctype=db.types.int),
		dict(cname="reminded", ctype=db.types.bool, default=0, notnull=True),
	],
	primary_keys=["event_id"]
))

db.ensure_table(dict(
	tname="bot_event_subs",
	columns=[
		dict(cname="event_id", ctype=db.types.int),
		dict(cname="user_id", ctype=db.types.int),
	],
	primary_keys=["event_id", "user_id"]
))

_next_check = 0
_tasks = set()  # strong refs so fire-and-forget tasks aren't garbage collected mid-run


# ---- time input -------------------------------------------------------------

def parse_timestamp(text):
	""" Unix time from a pasted Discord timestamp like <t:1793037600:F>, else None. """
	m = TIMESTAMP_RE.match(text.strip())
	return int(m.group(1)) if m else None


def parse_when(date_text, time_text):
	""" Unix time from a date ('2026-11-07') and a time of day ('20:00', '8pm'), read as UK time.
		Raises ValueError with a user-facing message if either part is malformed. """
	date_m = DATE_RE.match(date_text.strip())
	if not date_m:
		raise ValueError("Date must look like `2026-11-07`.")
	time_m = TIME_RE.match(time_text.strip())
	if not time_m:
		raise ValueError("Time must look like `20:00` or `8pm` (UK time).")

	hour, minute, meridiem = int(time_m.group(1)), int(time_m.group(2) or 0), (time_m.group(3) or "").lower()
	if meridiem:
		if not 1 <= hour <= 12:
			raise ValueError("Time must look like `20:00` or `8pm` (UK time).")
		hour = hour % 12 + (12 if meridiem == "pm" else 0)
	try:
		when = datetime(int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)), hour, minute, tzinfo=INPUT_TZ)
	except ValueError:
		raise ValueError("That isn't a real date or time.")
	return int(when.timestamp())


def date_choices(typed=""):
	""" {label: 'YYYY-MM-DD'} for the next few days, for the /event_add date autocomplete.
		Anything typed narrows the list; a typed full date is always offered back as-is. """
	today = datetime.now(INPUT_TZ).date()
	typed = typed.strip().lower()
	choices = {}
	for offset in range(DATE_CHOICES):
		day = today + timedelta(days=offset)
		label = f"{day:%a} {day.day} {day:%b}"
		if offset == 0:
			label = f"Today · {label}"
		elif offset == 1:
			label = f"Tomorrow · {label}"
		if not typed or typed in label.lower() or typed in day.isoformat():
			choices[label] = day.isoformat()
	if DATE_RE.match(typed) and typed not in choices.values():
		choices[typed] = typed
	return dict(list(choices.items())[:25])


# ---- storage ----------------------------------------------------------------

async def create(name, note, starts_at, created_by):
	return await db.insert('bot_events', dict(
		name=name, note=note or "", starts_at=starts_at, created_by=created_by, reminded=0
	))


async def get(event_id):
	return await db.select_one(
		['event_id', 'name', 'note', 'starts_at', 'created_by', 'reminded'], 'bot_events', where=dict(event_id=event_id)
	)


async def upcoming():
	""" Events that haven't expired yet, soonest first. """
	rows = await db.select(['event_id', 'name', 'note', 'starts_at', 'created_by', 'reminded'], 'bot_events')
	cutoff = time() - KEEP_AFTER_START
	return sorted((r for r in rows if r['starts_at'] > cutoff), key=lambda r: r['starts_at'])


async def subscriber_ids(event_id):
	rows = await db.select(['user_id'], 'bot_event_subs', where=dict(event_id=event_id))
	return [r['user_id'] for r in rows]


async def is_subscribed(event_id, user_id):
	return await db.select_one(['user_id'], 'bot_event_subs', where=dict(event_id=event_id, user_id=user_id)) is not None


async def subscribe(event_id, user_id):
	await db.insert('bot_event_subs', dict(event_id=event_id, user_id=user_id), on_dublicate='ignore')


async def unsubscribe(event_id, user_id):
	await db.delete('bot_event_subs', where=dict(event_id=event_id, user_id=user_id))


async def remove(event_id):
	await db.delete('bot_event_subs', where=dict(event_id=event_id))
	await db.delete('bot_events', where=dict(event_id=event_id))


# ---- announcing and reminding -----------------------------------------------

def _spawn(coro):
	task = asyncio.get_event_loop().create_task(coro)
	_tasks.add(task)
	task.add_done_callback(_tasks.discard)


def event_embed(event, footer=None):
	embed = Embed(title=f"📅 {event['name']}", colour=Colour(0x9b59b6))
	lines = [f"**<t:{event['starts_at']}:F>** (<t:{event['starts_at']}:R>)"]
	if event['note']:
		lines.append(event['note'])
	embed.description = "\n\n".join(lines)
	if footer:
		embed.set_footer(text=footer)
	return embed


def announce(event):
	""" Post the event with @everyone in every channel the bot is enabled in. Runs in the
		background — there can be many channels, and the slash command must answer within 3s. """
	_spawn(_announce(event))


async def _announce(event):
	posted = 0
	for qc in list(bot.queue_channels.values()):
		if (channel := dc.get_channel(qc.id)) is None:
			continue
		footer = f"Want a DM an hour before? {qc.cfg.prefix}event_sub {event['event_id']}"
		try:
			await channel.send(content="@everyone", embed=event_embed(event, footer))
			posted += 1
		except DiscordException as e:
			log.error(f"Events: failed to announce in #{getattr(channel, 'name', qc.id)}: {str(e)}")
	log.info(f"Events: announced #{event['event_id']} '{event['name']}' in {posted} channel(s).")


async def think(frame_time):
	global _next_check
	if frame_time < _next_check:
		return
	_next_check = frame_time + CHECK_INTERVAL
	_spawn(_tick())


async def _tick():
	try:
		now = time()
		rows = await db.select(['event_id', 'name', 'note', 'starts_at', 'created_by', 'reminded'], 'bot_events')
		for event in rows:
			if event['starts_at'] < now - KEEP_AFTER_START:
				await remove(event['event_id'])
			elif not event['reminded'] and event['starts_at'] - now <= REMIND_BEFORE:
				# Mark first: if the bot dies mid-send, a missed reminder beats sending everyone a second one.
				await db.update('bot_events', dict(reminded=1), keys=dict(event_id=event['event_id']))
				if event['starts_at'] > now:  # an event we were down for entirely is not worth a DM
					await _remind(event)
	except Exception as e:
		log.error(f"Events tick failed: {str(e)}\n{traceback.format_exc()}")


async def _remind(event):
	embed = event_embed(event)
	embed.title = f"⏰ Starting soon: {event['name']}"
	sent = failed = 0
	for user_id in await subscriber_ids(event['event_id']):
		try:
			user = dc.get_user(user_id) or await dc.fetch_user(user_id)
			await user.send(embed=embed)
			sent += 1
		except DiscordException:  # DMs closed, user left every shared server, account gone, ...
			failed += 1
		await asyncio.sleep(DM_SPACING)
	log.info(f"Events: reminded {sent} for #{event['event_id']} '{event['name']}' ({failed} couldn't be DMed).")
