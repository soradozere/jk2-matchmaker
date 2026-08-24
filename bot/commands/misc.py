__all__ = [
	'auto_ready', 'expire', 'default_expire', 'allow_offline', 'switch_dms', 'cointoss',
	'show_help', 'set_nick', 'commands_help', 'tz', 'urban'
]

import re
from time import time
from datetime import timedelta, datetime
from random import randint
from zoneinfo import ZoneInfo

from nextcord import Embed, Colour

from core.utils import seconds_to_str, find, discord_table
from core.database import db
from core.config import cfg

import bot

MAX_EXPIRE_TIME = timedelta(hours=12)

# (display label, IANA zone) — spans the regions this community actually plays out of.
MAJOR_TIMEZONES = [
	("Los Angeles", "America/Los_Angeles"),
	("Denver", "America/Denver"),
	("Chicago", "America/Chicago"),
	("New York", "America/New_York"),
	("London", "Europe/London"),
	("Berlin", "Europe/Berlin"),
	("Moscow", "Europe/Moscow"),
	("Mumbai", "Asia/Kolkata"),
	("Tokyo", "Asia/Tokyo"),
	("Sydney", "Australia/Sydney"),
]

_UD_LINK_RE = re.compile(r"[\[\]]")  # Urban Dictionary wraps cross-linked words in [brackets]


async def auto_ready(ctx, duration: timedelta = None):
	if not duration:
		duration = timedelta(seconds=min([60*5, ctx.qc.cfg.max_auto_ready]))

	if duration.total_seconds() > ctx.qc.cfg.max_auto_ready:
		raise ctx.Exc.ValueError(ctx.qc.gt("Maximum auto_ready duration is {duration}.").format(
			duration=seconds_to_str(ctx.qc.cfg.max_auto_ready)
		))

	if ctx.author.id in bot.auto_ready.keys():
		bot.auto_ready.pop(ctx.author.id)
		await ctx.success(ctx.qc.gt("Your automatic ready confirmation is now turned off."))
		return

	bot.auto_ready[ctx.author.id] = int(time()) + duration.total_seconds()
	await ctx.success(
		ctx.qc.gt("During next {duration} your match participation will be confirmed automatically.").format(
			duration=duration.__str__()
		)
	)


async def expire(ctx, duration: timedelta = None):
	if not duration:
		if task := bot.expire.get(ctx.qc, ctx.author):
			await ctx.reply(ctx.qc.gt("You have {duration} expire time left.").format(
				duration=seconds_to_str(task.at - int(time()))
			))
			return
		await ctx.reply(ctx.qc.gt("You don't have an expire timer set right now."))
		return

	if duration > MAX_EXPIRE_TIME:
		raise bot.Exc.ValueError(ctx.qc.gt("Expire time must be less than {time}.".format(
			time=MAX_EXPIRE_TIME.__str__()
		)))

	bot.expire.set(ctx.qc, ctx.author, duration.total_seconds())
	await ctx.success(ctx.qc.gt("Set your expire time to {duration}.").format(
		duration=duration.__str__()
	))


async def default_expire(ctx, duration: timedelta = None, afk: bool = None, clear: bool = None):

	def _expire_to_reply(seconds):
		if seconds == 0:
			return ctx.qc.gt("You will be removed from queues on AFK status by default.")
		elif seconds is None:
			return ctx.qc.gt("Your expire time value will fallback to guild's settings.")
		else:
			return ctx.qc.gt("Your default expire time is {time}.".format(time=seconds_to_str(seconds)))

	if duration is None and afk is None and clear is None:
		data = await db.select_one(['expire'], 'players', where={'user_id': ctx.author.id})
		seconds = None if not data else data['expire']
		await ctx.reply(_expire_to_reply(seconds))
		return

	seconds = None
	if duration:
		if duration > MAX_EXPIRE_TIME:
			raise bot.Exc.ValueError(ctx.qc.gt("Expire time must be less than {time}.".format(
				time=MAX_EXPIRE_TIME.__str__()
			)))
		seconds = duration.total_seconds()
	if afk:
		seconds = 0

	try:
		await db.insert('players', {'user_id': ctx.author.id, 'expire': seconds})
	except db.errors.IntegrityError:
		await db.update('players', {'expire': seconds}, keys={'user_id': ctx.author.id})
	await ctx.success(_expire_to_reply(seconds))


async def allow_offline(ctx):
	if ctx.author.id in bot.allow_offline:
		bot.allow_offline.remove(ctx.author.id)
		await ctx.success(ctx.qc.gt("Your offline immunity is **off**."))
	else:
		bot.allow_offline.append(ctx.author.id)
		await ctx.success(ctx.qc.gt("Your offline immunity is **on** until the next match."))


async def switch_dms(ctx):
	data = await db.select_one(('allow_dm',), 'players', where={'user_id': ctx.author.id})
	if data:
		allow_dm = 1 if data['allow_dm'] == 0 else 0
		await db.update('players', {'allow_dm': allow_dm}, keys={'user_id': ctx.author.id})
	else:
		allow_dm = 0
		await db.insert('players', {'allow_dm': allow_dm, 'user_id': ctx.author.id})

	if allow_dm:
		await ctx.success(ctx.qc.gt("Your DM notifications is now turned on."))
	else:
		await ctx.success(ctx.qc.gt("Your DM notifications is now turned off."))


async def cointoss(ctx, side: str = None):
	pick = 0
	if side in ["tails", ctx.qc.gt("tails")]:
		pick = 1

	result = randint(0, 1)
	if pick == result:
		await ctx.reply(ctx.qc.gt("{member} won, its **{side}**!").format(
			member=ctx.author.mention, side=ctx.qc.gt(["heads", "tails"][result])
		))
	else:
		await ctx.reply(ctx.qc.gt("{member} lost, its **{side}**!").format(
			member=ctx.author.mention, side=ctx.qc.gt(["heads", "tails"][result])
		))


async def tz(ctx):
	now = datetime.now(ZoneInfo("UTC"))
	rows = [
		[label, now.astimezone(ZoneInfo(zone)).strftime("%I:%M %p").lstrip("0"), now.astimezone(ZoneInfo(zone)).strftime("%Z")]
		for label, zone in MAJOR_TIMEZONES
	]
	await ctx.reply(
		"🌍 " + ctx.qc.gt("Current time around the world") + "\n" +
		discord_table([ctx.qc.gt("Location"), ctx.qc.gt("Time"), "TZ"], rows)
	)


async def urban(ctx, term: str = None):
	if not term:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Usage: {cmd}").format(cmd=f"`{ctx.qc.cfg.prefix}urban <term>`"))

	try:
		results = await bot.urban.define(term)
	except bot.urban.UrbanError as e:
		raise bot.Exc.NotFoundError(str(e))
	if not results:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No definition found for **{term}**.").format(term=term))

	d = results[0]
	definition = _UD_LINK_RE.sub("", d.get('definition') or "")[:900]
	example = _UD_LINK_RE.sub("", d.get('example') or "")[:500]

	embed = Embed(
		title=f"📖 {d.get('word', term)}",
		url=d.get('permalink'),
		colour=Colour(0x1d2439),
		description=definition
	)
	if example:
		embed.add_field(name=ctx.qc.gt("Example"), value=example, inline=False)
	embed.add_field(name="👍", value=str(d.get('thumbs_up', 0)), inline=True)
	embed.add_field(name="👎", value=str(d.get('thumbs_down', 0)), inline=True)
	embed.set_footer(text="urbandictionary.com")
	await ctx.reply(embed=embed)


async def show_help(ctx, queue: str = None):
	if queue is None:
		if not ctx.qc.cfg.description:
			await ctx.reply_dm(cfg.HELP+"\nYou can edit this message with command `/channel set description`.")
		else:
			await ctx.reply_dm(ctx.qc.cfg.description)
		return
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")

	await ctx.reply_dm(q.cfg.description or ctx.qc.gt('Specified queue has no help answer set.'))


async def commands_help(ctx, queue: str = None):
	p = ctx.qc.cfg.prefix
	embed = Embed(
		title="JK2 Matchmaker — commands",
		colour=Colour(0x7289DA),
		description=f"Everyday commands work with the `{p}` prefix or as `/` slash commands."
	)
	embed.add_field(name="Queue", value="\n".join([
		f"`{p}j` / `++` — join the queue",
		f"`{p}l` / `--` — leave the queue",
		f"`{p}who` — see who's in the queue",
	]), inline=False)
	soracle_on = bot.soracle.enabled()
	match_lines = [
		f"`{p}capfor <team>` — become a captain during manual picks",
		f"`{p}p @player` — pick a player (captains)",
		f"`{p}rl` — report a loss (losing captain)",
		f"`{p}subme` · `{p}subfor @player` — substitutions",
	]
	if soracle_on:
		match_lines.insert(0, f"`{p}rebalance` — captains: re-apply Perfect Balance")
		match_lines.insert(0, f"`{p}manual` — admins: switch a match to manual picks")
	embed.add_field(name="Match", value="\n".join(match_lines), inline=False)
	if soracle_on:
		embed.add_field(name="📊 Leaderboards", value=" · ".join(
			f"`{p}{c}`" for c in (
				"lb", "month", "kills", "deaths", "caps", "grabs", "bc",
				"dbs", "dfa", "doom", "flaghold", "returns", "streak"
			)
		), inline=False)
		embed.add_field(name="👤 Your stats", value=" · ".join(
			f"`{p}{c}`" for c in (
				"tier", "stats", "rank", "achievements", "lastgame",
				"redblue", "nemesis", "friend", "curse"
			)
		), inline=False)
		embed.add_field(name="🏆 Monthly awards", value=" · ".join(
			f"`{p}{c}`" for c in ("potm", "rivals", "duos", "wrapped")
		), inline=False)
	else:
		embed.add_field(name="Stats & ranks", value="\n".join([
			f"`{p}rank [@player]` — Elo rank profile",
			f"`{p}lb` — leaderboard",
		]), inline=False)
	embed.add_field(name="JK2 servers", value="\n".join([
		f"`{p}servers` — live server status",
		f"`{p}pug` — toggle the pug ping role",
	]), inline=False)
	embed.add_field(name="Fun", value="\n".join([
		f"`{p}tz` — current time in major timezones",
		f"`{p}urban <term>` — Urban Dictionary lookup",
		f"`{p}cointoss [heads/tails]` — flip a coin",
	]), inline=False)
	await ctx.reply_dm(embed=embed)


async def set_nick(ctx, nick: str):
	data = await db.select_one(
		['rating'], 'qc_players',
		where={'channel_id': ctx.author.id, 'user_id': ctx.author.id}
	)
	if not data or data['rating'] is None:
		rating = ctx.qc.rating.init_rp
	else:
		rating = data['rating']

	await ctx.author.edit(nick=f"[{rating}] " + nick)
	await ctx.ignore(ctx.qc.gt("Done."))
