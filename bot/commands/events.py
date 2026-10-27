__all__ = ['event_add', 'events', 'event_sub', 'event_unsub', 'event_remove']

from nextcord import Embed, Colour

import bot
from bot import events_calendar as cal


MAX_LISTED = 25  # attendees named per event; the rest are counted, to keep the embed under Discord's size limit


def _line(e, subs):
	""" One event's block for =events. Attendees are <@id> mentions, which an embed renders as names without pinging. """
	lines = [f"**#{e['event_id']} · {e['name']}**", f"<t:{e['starts_at']}:F> (<t:{e['starts_at']}:R>)"]
	if e['note']:
		lines.append(e['note'])
	if subs:
		shown = " ".join(f"<@{uid}>" for uid in subs[:MAX_LISTED])
		more = f" +{len(subs) - MAX_LISTED} more" if len(subs) > MAX_LISTED else ""
		lines.append(f"**Attendees ({len(subs)})**\n{shown}{more}")
	else:
		lines.append("*No attendees yet*")
	return "\n".join(lines)


async def _pick(ctx, event_id):
	""" The event a command refers to. With a couple of events at a time, leaving the
		number off is fine as long as only one is coming up. """
	upcoming = await cal.upcoming()
	if event_id is None:
		if len(upcoming) == 1:
			return upcoming[0]
		raise bot.Exc.SyntaxError(ctx.qc.gt("Which event? Give its number from `{prefix}events`.").format(prefix=ctx.qc.cfg.prefix))
	if (event := next((e for e in upcoming if e['event_id'] == event_id), None)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No upcoming event with that number."))
	return event


async def event_add(ctx, name: str, date: str = None, time: str = None, timestamp: int = None, note: str = None):
	""" Create an event and announce it everywhere. The start comes either from `timestamp` (unix)
		or from `date` + `time` (UK time). """
	ctx.check_perms(ctx.Perms.MODERATOR)
	name, note = (name or "").strip(), (note or "").strip()
	if not name:
		raise bot.Exc.SyntaxError(ctx.qc.gt("The event needs a name."))
	if len(name) > cal.MAX_NAME or len(note) > cal.MAX_NOTE:
		raise bot.Exc.ValueError(ctx.qc.gt("Name is limited to {n} characters and the note to {m}.").format(
			n=cal.MAX_NAME, m=cal.MAX_NOTE
		))

	if timestamp is None:
		try:
			timestamp = cal.parse_when(date or "", time or "")
		except ValueError as e:
			raise bot.Exc.SyntaxError(ctx.qc.gt(str(e)))
	if timestamp <= cal.time() + 60:
		raise bot.Exc.ValueError(ctx.qc.gt("That time has already passed."))

	event_id = await cal.create(name, note, timestamp, ctx.author.id)
	event = await cal.get(event_id)
	await ctx.success(ctx.qc.gt(
		"Event **#{id} · {name}** set for <t:{ts}:F> (<t:{ts}:R>) — announcing it everywhere now. "
		"Wrong? `{prefix}event_remove {id}` cancels it."
	).format(id=event_id, name=name, ts=timestamp, prefix=ctx.qc.cfg.prefix))
	cal.announce(event)


async def events(ctx):
	upcoming = await cal.upcoming()
	if not upcoming:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No events planned."))
	blocks = [_line(e, await cal.subscriber_ids(e['event_id'])) for e in upcoming]
	embed = Embed(title="📅 Upcoming events", colour=Colour(0x9b59b6), description="\n\n".join(blocks)[:4096])
	embed.set_footer(text=f"{ctx.qc.cfg.prefix}event_sub <number> — get a DM an hour before")
	await ctx.reply(embed=embed)


async def event_sub(ctx, event_id: int = None):
	event = await _pick(ctx, event_id)
	if await cal.is_subscribed(event['event_id'], ctx.author.id):
		raise bot.Exc.ValueError(ctx.qc.gt("You're already getting a reminder for **{name}**.").format(name=event['name']))
	await cal.subscribe(event['event_id'], ctx.author.id)
	text = ctx.qc.gt("You'll get a DM an hour before **{name}** (<t:{ts}:R>). Make sure you allow DMs from server members.")
	if event['reminded']:
		text = ctx.qc.gt("**{name}** (<t:{ts}:R>) is under an hour away and its reminders already went out, so you won't get a DM.")
	await ctx.success(text.format(name=event['name'], ts=event['starts_at']))


async def event_unsub(ctx, event_id: int = None):
	event = await _pick(ctx, event_id)
	if not await cal.is_subscribed(event['event_id'], ctx.author.id):
		raise bot.Exc.ValueError(ctx.qc.gt("You weren't subscribed to **{name}**.").format(name=event['name']))
	await cal.unsubscribe(event['event_id'], ctx.author.id)
	await ctx.success(ctx.qc.gt("No reminder for **{name}** then.").format(name=event['name']))


async def event_remove(ctx, event_id: int = None):
	ctx.check_perms(ctx.Perms.MODERATOR)
	event = await _pick(ctx, event_id)
	await cal.remove(event['event_id'])
	await ctx.success(ctx.qc.gt("Cancelled **#{id} · {name}**. Subscribers won't be notified.").format(
		id=event['event_id'], name=event['name']
	))
