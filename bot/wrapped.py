# -*- coding: utf-8 -*-
""" Monthly "Wrapped" summary: a single embed crowning the month's awards.
	Auto-published on the 1st (pinging @everyone in channels with wrapped_channel on),
	and re-shown anytime via =wrapped. Both report the last completed month. """

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from nextcord import Embed, Colour, DiscordException

import bot
from bot import soracle
from core.client import dc
from core.console import log

CHECK_INTERVAL = 30 * 60  # how often the think loop re-checks the date
PUBLISH_TZ = ZoneInfo("Europe/London")  # handles BST/GMT automatically
PUBLISH_HOUR = 17  # 5pm UK on the 1st
_next_check = 0


def _prev_month(now):
	""" (year, month) of the calendar month before `now`. """
	return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


def _top(players, key, reverse=True):
	ranked = sorted((p for p in players if p.get(key)), key=lambda p: p[key], reverse=reverse)
	return ranked[0] if ranked else None


def build_embed(report, agg):
	""" Compose the Wrapped embed from a month's report + aggregates payloads.
		Returns None if the month had no matches. """
	players = agg.get('players') or []
	match_count = agg.get('matchCount') or 0
	if not match_count:
		return None

	month = report.get('month', 'last month')
	embed = Embed(title=f"🏆 JK2 — {month} Wrapped", colour=Colour(0xf1c40f), url=soracle.cfg.SORACLE_API_URL)
	lines = [f"*That's a wrap on {month} — **{match_count}** matches played!*\n"]

	if star := report.get('starPlayer'):
		lines.append("⭐ **Star Player** — **{n}** ({w}W/{l}L, rating {s})".format(
			n=star['name'], w=star.get('wins', 0), l=star.get('losses', 0), s=star.get('avgScore', 0)
		))
	if frag := _top(players, 'kills'):
		kd = f"{frag['kills'] / frag['deaths']:.2f}" if frag.get('deaths') else "∞"
		lines.append(f"🔥 **Top Fragger** — **{frag['name']}** ({frag['kills']} kills, {kd} K/D)")

	# Most efficient capper: regular cappers (caps >= 40% of max), fewest min/cap.
	min_matches = max(1, -(-match_count * 3 // 10))
	qualified = [p for p in players if p.get('matches', 0) >= min_matches]
	max_caps = max((p.get('captures', 0) for p in qualified), default=0)
	cappers = [p for p in qualified if p.get('captures', 0) >= max_caps * 0.4 and p.get('captures') and p.get('flagHoldMs')]
	if cappers:
		c = min(cappers, key=lambda p: p['flagHoldMs'] / p['captures'])
		lines.append(f"🚩 **Top Capper** — **{c['name']}** (1 cap / {c['flagHoldMs'] / 60000 / c['captures']:.1f} min)")

	if dbs := _top(players, 'dbsKills'):
		lines.append(f"💥 **DBS King** — **{dbs['name']}** ({dbs['dbsKills']})")
	if grabs := _top(players, 'flagGrabs'):
		lines.append(f"✋ **Most Flag Grabs** — **{grabs['name']}** ({grabs['flagGrabs']})")
	if (streaks := report.get('streaks')):
		s = streaks[0]
		lines.append(f"📈 **Longest Streak** — **{s['name']}** ({s['streak']} in a row)")
	if (rivalries := report.get('rivalries')):
		r = rivalries[0]
		p2w = r['count'] - r['player1Wins']
		lead = (f"{r['player1']} leads {r['player1Wins']}–{p2w}" if r['player1Wins'] >= p2w
				else f"{r['player2']} leads {p2w}–{r['player1Wins']}")
		lines.append(f"⚔️ **Biggest Rivalry** — **{r['player1']} vs {r['player2']}** ({r['count']} meetings, {lead})")
	if rb := report.get('redBlue'):
		total = rb.get('total') or 0
		if total:
			lines.append("🔥 **Red vs Blue** 💧 — Red {r} / Blue {b}".format(r=rb.get('redWins', 0), b=rb.get('blueWins', 0)))

	lines.append(f"\n*See the full breakdown at {soracle.cfg.SORACLE_API_URL} · type `=wrapped` to see this again.*")
	embed.description = "\n".join(lines)
	return embed


async def render_month(year, month):
	""" Fetch a month's data and build its embed (None if the month is empty). """
	report = await soracle.fetch_monthly_report(year, month)
	agg = await soracle.fetch_monthly_aggregates(year, month)
	return build_embed(report, agg)


async def show(ctx):
	""" =wrapped — the last completed month, falling back to the current month if that's empty. """
	now = datetime.now(timezone.utc)
	year, month = _prev_month(now)
	try:
		embed = await render_month(year, month)
		if embed is None:  # nothing last month yet (e.g. before the first full month)
			embed = await render_month(now.year, now.month)
	except soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if embed is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No wrapped summary available yet."))
	await ctx.reply(embed=embed)


async def think(frame_time):
	global _next_check
	if frame_time < _next_check:
		return
	_next_check = frame_time + CHECK_INTERVAL

	now = datetime.now(PUBLISH_TZ)
	month_key = now.strftime("%Y-%m")
	if bot.wrapped_published == month_key:
		return  # already handled this month's wrap

	# Publish once we're at/after the 1st of the (UK) month at 5pm. Using a target
	# rather than "day == 1" means a brief outage over the 1st won't skip the month.
	target = now.replace(day=1, hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
	if now < target:
		return

	year, month = _prev_month(now)
	try:
		embed = await render_month(year, month)
	except soracle.SoracleError as e:
		log.error(f"Wrapped auto-publish failed to fetch {year}-{month}: {str(e)}")
		return
	# Mark as handled even if the month was empty, so we don't retry all day.
	bot.wrapped_published = month_key
	bot.save_state()
	if embed is None:
		log.info(f"Wrapped: no matches for {year}-{month}, nothing to publish.")
		return

	posted = 0
	for qc in bot.queue_channels.values():
		if not getattr(qc.cfg, 'wrapped_channel', False):
			continue
		if (channel := dc.get_channel(qc.id)) is None:
			continue
		try:
			await channel.send(content="@everyone", embed=embed)
			posted += 1
		except DiscordException as e:
			log.error(f"Wrapped: failed to post in #{getattr(channel, 'name', qc.id)}: {str(e)}")
	log.info(f"Wrapped: published {year}-{month} to {posted} channel(s).")
