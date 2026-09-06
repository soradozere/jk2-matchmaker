__all__ = [
	'soracle_info', 'monthly_stats', 'dbs_leaderboard', 'dfa_leaderboard',
	'kills_leaderboard', 'deaths_leaderboard', 'caps_leaderboard', 'potm', 'rivals',
	'grabs_leaderboard', 'bc_leaderboard', 'flaghold_leaderboard', 'returns_leaderboard',
	'streaks_leaderboard', 'doom_leaderboard', 'redblue', 'nemesis', 'friend', 'curse', 'duos', 'wrapped', 'last_game_soracle',
	'balance_options', 'achievements', 'impact_leaderboard'
]

import re
from math import ceil
from random import choice
from datetime import datetime, timezone
from urllib.parse import quote

from nextcord import Member, Embed, Colour

from core.utils import find, get_nick

import bot
from bot import soracle

# Site role names -> community names
ROLE_DISPLAY = {"Cleaner": "BC"}

# Public site for player-facing links (embed titles, profile links). See
# soracle.site_url() for why this is not SORACLE_API_URL.
SITE_URL = soracle.site_url()

UNLINKED = "**{name}** isn't linked to a site profile yet — an admin can link them at {url}"


def _profile_url(name):
	""" Public profile URL for a player name — same slug rules as the site
		(lowercase, whitespace -> dashes, URI-encoded). """
	return f"{SITE_URL}/player/{quote(re.sub(r'\\s+', '-', name.strip().lower()))}"


async def soracle_info(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_player(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	# The equipped title tints the embed. It's shown as a rarity dot + name
	# beneath the slogan — no source, matching the other title displays.
	# Older Soracle deploys omit the field, so it degrades to no title.
	title = data.get('title')
	accent = RARITY_COLOUR.get(title.get('rarity'), 0x7289DA) if title else 0x7289DA
	embed = Embed(title=f"__{data.get('name') or get_nick(target)}__", colour=Colour(accent))
	desc_lines = []
	if tooltip := data.get('tooltip'):
		desc_lines.append(f"*{tooltip}*")
	if title:
		desc_lines.append("{dot} **{t}**".format(dot=RARITY_DOT.get(title.get('rarity'), ''), t=title['title']))
	if desc_lines:
		embed.description = "\n".join(desc_lines)
	embed.add_field(name="Tier", value=f"**{data.get('tier', '?')}**", inline=True)
	roles = data.get('roles') or {}
	if isinstance(roles, dict):
		roles_str = "\n".join(f"{ROLE_DISPLAY.get(name, name)}: **{score}**" for name, score in roles.items())
	else:
		roles_str = ", ".join(map(str, roles))
	embed.add_field(name="Roles", value=roles_str or "—", inline=True)
	if target.display_avatar:
		embed.set_thumbnail(url=target.display_avatar.url)
	await ctx.reply(embed=embed)


def _board_lines(ctx, top, unit=""):
	""" Render a top-5 board's rows, or the empty-state string. """
	if not top:
		return ctx.qc.gt("Nothing recorded this month yet.")
	return "\n".join(
		f"**{n + 1}.** {r['name']} — **{r['value']}**{unit}" for n, r in enumerate(top)
	)


def _kills_with_attempts_lines(ctx, top):
	""" Like _board_lines, but appends each row's companion count — the attempts
		behind the kills, so the board reads as a hit rate rather than a raw
		total. Falls back to "?" on an older Soracle deploy that doesn't send
		`companion` yet, rather than dropping the board. """
	if not top:
		return ctx.qc.gt("Nothing recorded this month yet.")
	return "\n".join(
		f"**{n + 1}.** {r['name']} — **{r['value']}** (attempts: {r.get('companion', '?')})"
		for n, r in enumerate(top)
	)


async def _stat_leaderboard(ctx, stat, title, unit="", all_time=False):
	""" Simple top-5-by-summed-stat board (=dfa, =grabs, ...). """
	try:
		data = await soracle.fetch_stat_leaderboard(stat, all_time=all_time)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	embed = Embed(title=f"{title} — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	embed.description = _board_lines(ctx, data.get('top'), unit)
	await ctx.reply(embed=embed)


async def dbs_leaderboard(ctx):
	# Two boards for the price of one: most DBS kills, and most DBS *return* kills
	# (killing the enemy flag carrier with a DBS). Both summed over the month.
	try:
		kills = await soracle.fetch_stat_leaderboard('dbs_kills')
		returns = await soracle.fetch_stat_leaderboard('dbs_returns')
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	embed = Embed(title=f"DBS leaderboards — {kills.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	embed.add_field(name="🗡️ Top DBS killers", value=_board_lines(ctx, kills.get('top')), inline=False)
	embed.add_field(name="🚩 Top DBS return kills", value=_board_lines(ctx, returns.get('top')), inline=False)
	await ctx.reply(embed=embed)


async def dfa_leaderboard(ctx):
	# Same two-board shape as =dbs: most DFA kills, and most DFA *return* kills
	# (killing the enemy flag carrier with a DFA). Both summed over the month.
	#
	# Attempts ride along on the kills board rather than getting a board of their
	# own: ranking by raw attempts just crowns whoever spammed DFA the most, which
	# says nothing about skill. Beside the kill count it's the useful half of a
	# hit rate ("897, from 4664 attempts"), which is the number people actually
	# want. Soracle sends it as each row's `companion` — see COMPANION_STATS in
	# app/api/bot/leaderboard/[stat]/route.ts over there.
	try:
		kills = await soracle.fetch_stat_leaderboard('dfa_kills')
		returns = await soracle.fetch_stat_leaderboard('dfa_returns')
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	embed = Embed(title=f"DFA leaderboards — {kills.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	embed.add_field(name="🗡️ Top DFA killers", value=_kills_with_attempts_lines(ctx, kills.get('top')), inline=False)
	embed.add_field(name="🚩 Top DFA return kills", value=_board_lines(ctx, returns.get('top')), inline=False)
	await ctx.reply(embed=embed)


async def grabs_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'flag_grabs', "Top flag grabbers")


async def doom_leaderboard(ctx):
	# ALL-TIME, unlike every other board here. Doom kills run about one a week
	# across the whole community, so a monthly board would usually be empty or a
	# single player on 1.
	await _stat_leaderboard(ctx, 'doom_kills', "Top doom throwers", all_time=True)


async def bc_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'base_cleaner', "Top base cleaners")


async def impact_leaderboard(ctx, page: int = 1):
	""" =impact / =impact 2 / =impact 3 -- top 10 players by impact this
		month, paginated 10 at a time (same paging pattern as the vanilla
		=lb) -- month-to-date, same as the other stat boards (=kills, =caps). """
	page = (page or 1) - 1
	try:
		data = await soracle.fetch_stat_leaderboard('impact')
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	full = data.get('top') or []
	pages = ceil(len(full) / 10) or 1
	rows = full[page * 10:(page + 1) * 10]
	if not rows:
		raise bot.Exc.NotFoundError(
			ctx.qc.gt("Nothing recorded this month yet.") if page == 0 else ctx.qc.gt("That page doesn't exist.")
		)

	embed = Embed(
		title=f"Top impact — {data.get('month', 'this month')} — page {page + 1} of {pages}",
		colour=Colour(0x50e3c2), url=SITE_URL
	)
	embed.description = "\n".join(
		f"**{(page * 10) + n + 1}.** {r['name']} — **{r['value']}**" for n, r in enumerate(rows)
	)
	await ctx.reply(embed=embed)


async def _monthly_players(ctx):
	""" Fetch this month's aggregates and the 30%-of-matches qualifier threshold. """
	try:
		data = await soracle.fetch_monthly_aggregates()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	min_matches = max(1, ceil((data.get('matchCount') or 0) * 0.3))
	return data, data.get('players') or [], min_matches


async def potm(ctx):
	try:
		data = await soracle.fetch_monthly_report()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	star = data.get('starPlayer')
	embed = Embed(
		title=f"⭐ Star Player of the Month — {data.get('month', 'this month')}",
		colour=Colour(0xf1c40f),
		url=SITE_URL
	)
	if not star:
		embed.description = ctx.qc.gt("No qualifying player yet this month.")
	else:
		games = star.get('wins', 0) + star.get('losses', 0)
		winrate = int(star['wins'] * 100 / games) if games else 0
		embed.description = "## {name}\n**{w}W / {l}L** ({wr}% win rate) over {m} games\n**{s}** win-value per game".format(
			name=star['name'], w=star.get('wins', 0), l=star.get('losses', 0),
			wr=winrate, m=star.get('matches', 0), s=star.get('avgScore', 0)
		)
		embed.set_footer(text="Beating the odds > stat-padding. Underdog wins = 🔥, easy wins = meh, losses = 0. 🐐")
	await ctx.reply(embed=embed)


async def rivals(ctx):
	try:
		data = await soracle.fetch_monthly_report()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	rivalries = data.get('rivalries') or []
	embed = Embed(
		title=f"Top rivalries — {data.get('month', 'this month')}",
		colour=Colour(0x50e3c2),
		url=SITE_URL
	)
	if not rivalries:
		embed.description = ctx.qc.gt("No rivalries have formed yet this month.")
	else:
		lines = []
		for i, r in enumerate(rivalries):
			p1, p2, count, p1w = r['player1'], r['player2'], r['count'], r['player1Wins']
			p2w = count - p1w
			if p1w > p2w:
				standing = f"{p1} leads **{p1w}–{p2w}**"
			elif p2w > p1w:
				standing = f"{p2} leads **{p2w}–{p1w}**"
			else:
				standing = f"all square **{p1w}–{p2w}**"
			lines.append(f"**{i + 1}.** {p1} vs {p2} — faced **{count}** times · {standing}")
		embed.description = "\n".join(lines)
		embed.set_footer(text="The most-contested matchups — ranked by how close the head-to-head is, not who plays most.")
	await ctx.reply(embed=embed)


async def duos(ctx):
	try:
		data = await soracle.fetch_monthly_report()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	pairs = data.get('duos') or []
	embed = Embed(
		title=f"Top duos — {data.get('month', 'this month')}",
		colour=Colour(0x4ae24a),
		url=SITE_URL
	)
	if not pairs:
		embed.description = ctx.qc.gt("No duos have formed yet this month.")
	else:
		lines = []
		for i, d in enumerate(pairs):
			pct = round(d['wins'] * 100 / d['games']) if d['games'] else 0
			lines.append(f"**{i + 1}.** {d['player1']} & {d['player2']} — **{pct}%** ({d['wins']} of {d['games']})")
		embed.description = "\n".join(lines)
		embed.set_footer(text="The month's best-winning team-mate pairs — ranked by win rate together (min 4 games).")
	await ctx.reply(embed=embed)


async def wrapped(ctx):
	await bot.wrapped.show(ctx)


async def streaks_leaderboard(ctx):
	try:
		data = await soracle.fetch_monthly_report()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	streaks = data.get('streaks') or []
	embed = Embed(title=f"Longest win streaks — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not streaks:
		embed.description = ctx.qc.gt("No win streaks yet this month.")
	else:
		embed.description = "\n".join(
			f"**{i + 1}.** {s['name']} — **{s['streak']}** in a row" for i, s in enumerate(streaks)
		)
	await ctx.reply(embed=embed)


async def redblue(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_redblue(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	red, blue = data.get('red') or {}, data.get('blue') or {}
	embed = Embed(title=f"🔥 Red vs Blue 💧 — {data.get('name') or get_nick(target)}", colour=Colour(0x50e3c2), url=SITE_URL)

	def _side(emoji, label, s):
		g = s.get('games') or 0
		if not g:
			return f"{emoji} {label} — no games yet"
		w, l, d = s.get('wins', 0), s.get('losses', 0), s.get('draws', 0)
		return "{e} {lab} — **{w}–{l}**{d} · **{p}%** over {g}".format(
			e=emoji, lab=label, w=w, l=l,
			d=f"–{d}D" if d else "", p=round(w * 100 / g), g=g
		)

	if not (red.get('games') or blue.get('games')):
		embed.description = ctx.qc.gt("No recorded games yet.")
	else:
		embed.description = f"{_side('🔥', 'Red base', red)}\n{_side('💧', 'Blue base', blue)}"
	embed.set_footer(text=f"All-time base record. For global stats, go to {SITE_URL}/stats")
	await ctx.reply(embed=embed)


async def nemesis(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_nemesis(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	nemeses = data.get('nemeses')
	if nemeses is None:  # pre-top-3 Soracle: fall back to the single nemesis
		nemeses = [n] if (n := data.get('nemesis')) else []
	title = "Nemesis" if len(nemeses) <= 1 else "Nemeses"
	embed = Embed(title=f"{title} — {data.get('name') or get_nick(target)}", colour=Colour(0xe24b4a), url=SITE_URL)

	def _pct(nem):
		return round(nem['theirWins'] * 100 / nem['meetings']) if nem['meetings'] else 0

	if not nemeses:
		embed.description = ctx.qc.gt("No nemesis yet this month — not enough games against any one opponent.")
	elif len(nemeses) == 1:
		nem = nemeses[0]
		embed.description = "**{opp}** has beaten you in **{pct}%** of your meetings this month (**{tw} of {meet}**; you've won **{mw}**).".format(
			opp=nem['name'], pct=_pct(nem), tw=nem['theirWins'], mw=nem['myWins'], meet=nem['meetings']
		)
	else:
		embed.description = "\n".join(
			"**{i}.** **{opp}** — beaten you **{pct}%** (**{tw} of {meet}**)".format(
				i=i + 1, opp=nem['name'], pct=_pct(nem), tw=nem['theirWins'], meet=nem['meetings']
			)
			for i, nem in enumerate(nemeses)
		)
		embed.set_footer(text="Your worst head-to-heads this month — ranked by their win rate against you.")
	await ctx.reply(embed=embed)


async def friend(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_friend(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	friends = data.get('friends')
	if friends is None:  # pre-top-3 Soracle: fall back to the single friend
		friends = [f] if (f := data.get('friend')) else []
	title = "Best teammate" if len(friends) <= 1 else "Best teammates"
	embed = Embed(title=f"{title} — {data.get('name') or get_nick(target)}", colour=Colour(0x4ae24a), url=SITE_URL)

	def _pct(fr):
		return round(fr['wins'] * 100 / fr['games']) if fr['games'] else 0

	if not friends:
		embed.description = ctx.qc.gt("No best teammate yet this month — not enough games alongside any one player.")
	elif len(friends) == 1:
		fr = friends[0]
		embed.description = "You win **{pct}%** of games alongside **{name}** this month (**{w} of {g}**).".format(
			name=fr['name'], pct=_pct(fr), w=fr['wins'], g=fr['games']
		)
	else:
		embed.description = "\n".join(
			"**{i}.** **{name}** — **{pct}%** together (**{w} of {g}**)".format(
				i=i + 1, name=fr['name'], pct=_pct(fr), w=fr['wins'], g=fr['games']
			)
			for i, fr in enumerate(friends)
		)
		embed.set_footer(text="Your best team-mates this month — ranked by win rate on the same team.")
	await ctx.reply(embed=embed)


async def curse(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_curse(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	curses = data.get('curses')
	if curses is None:  # single-curse fallback, mirrors friend/nemesis
		curses = [c] if (c := data.get('curse')) else []
	title = "Curse" if len(curses) <= 1 else "Curses"
	embed = Embed(title=f"{title} — {data.get('name') or get_nick(target)}", colour=Colour(0xc0392b), url=SITE_URL)

	def _pct(cr):
		return round(cr['losses'] * 100 / cr['games']) if cr['games'] else 0

	if not curses:
		embed.description = ctx.qc.gt("No curse yet this month — not enough games alongside any one player.")
	elif len(curses) == 1:
		cr = curses[0]
		embed.description = "You **lose {pct}%** of games alongside **{name}** this month (**{l} of {g}**).".format(
			name=cr['name'], pct=_pct(cr), l=cr['losses'], g=cr['games']
		)
	else:
		embed.description = "\n".join(
			"**{i}.** **{name}** — **{pct}%** losses together (**{l} of {g}**)".format(
				i=i + 1, name=cr['name'], pct=_pct(cr), l=cr['losses'], g=cr['games']
			)
			for i, cr in enumerate(curses)
		)
		embed.set_footer(text="The team-mates you lose most alongside this month — ranked by loss rate on the same team.")
	await ctx.reply(embed=embed)


def _time_ago(iso):
	""" Human "x ago" for an ISO-8601 UTC timestamp (timezone-agnostic for =lg). """
	if not iso:
		return None
	try:
		then = datetime.fromisoformat(iso.replace('Z', '+00:00'))
	except (ValueError, AttributeError):
		return None
	secs = int((datetime.now(timezone.utc) - then).total_seconds())
	if secs < 60:
		return "just now"
	mins, hours, days = secs // 60, secs // 3600, secs // 86400
	unit = lambda n, name: f"{n} {name}{'' if n == 1 else 's'}"
	if days:
		rem_h = (secs % 86400) // 3600
		parts = [unit(days, "day")] + ([unit(rem_h, "hour")] if rem_h else [])
	elif hours:
		rem_m = (secs % 3600) // 60
		parts = [unit(hours, "hour")] + ([unit(rem_m, "minute")] if rem_m else [])
	else:
		parts = [unit(mins, "minute")]
	return ", ".join(parts) + " ago"


async def last_game_soracle(ctx, player: Member = None):
	""" In-depth view of the last match recorded on Soracle (=lg). With a player
		(=lg @player), shows that player's last recorded game. """
	target = await ctx.get_member(player) if player else None
	if player and not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_last_match(target.id if target else None)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		if target:
			raise bot.Exc.NotFoundError(
				f"No recorded games found for **{get_nick(target)}** (they may not be linked)."
			)
		raise bot.Exc.NotFoundError(ctx.qc.gt("No matches have been recorded yet."))

	winner = data.get('winner')
	colour = Colour(0xe24b4a) if winner == 'Red' else Colour(0x4a90e2) if winner == 'Blue' else Colour(0x95a5a6)
	when = _time_ago(data.get('date')) or "recently"

	heading = f"{get_nick(target)}'s last game" if target else "Last game"
	embed = Embed(title=f"{heading} — {when}", colour=colour, url=SITE_URL)
	result = ctx.qc.gt("Tie") if winner == 'Tie' else f"{winner} win"
	embed.description = "🔥 **Red {rs}** — **{bs} Blue** 💧 · {result} · {mt} pick".format(
		rs=data.get('redScore', 0), bs=data.get('blueScore', 0), result=result,
		mt=(data.get('matchType') or 'manual').capitalize()
	)

	stats = data.get('stats') or []

	if target:
		# Just the queried player's own line for that game, not the full scoreboard.
		me = data.get('playerName')
		mine = next((s for s in stats if s.get('name') == me), None)
		team = (mine or {}).get('team') or (
			'Red' if me in (data.get('redTeam') or []) else 'Blue' if me in (data.get('blueTeam') or []) else None
		)
		outcome = ctx.qc.gt("draw") if winner == 'Tie' else (ctx.qc.gt("won") if team == winner else ctx.qc.gt("lost"))
		if mine:
			line = "Score **{s}** · {c} caps · {r} returns · {k}/{d} K/D".format(
				s=mine.get('score', 0), c=mine.get('caps', 0), r=mine.get('returns', 0),
				k=mine.get('kills', 0), d=mine.get('deaths', 0)
			)
		else:
			line = ctx.qc.gt("No detailed stats recorded for this game.")
		embed.add_field(name=f"{me} ({team}) — {outcome}" if team else f"{me} — {outcome}", value=line, inline=False)
	else:
		by_team = {'Red': [], 'Blue': []}
		for s in stats:
			if s.get('team') in by_team:
				by_team[s['team']].append(s)

		def team_value(team_name, roster):
			rows = by_team[team_name]
			if rows:
				rows = sorted(rows, key=lambda r: r.get('score', 0), reverse=True)
				lines = ["{name} — **{s}**".format(name=r.get('name', '?'), s=r.get('score', 0)) for r in rows]
			else:
				lines = list(roster or []) or ["—"]
			return "\n".join(lines)[:1024]

		embed.add_field(name=f"🔥 Red ({data.get('redScore', 0)})", value=team_value('Red', data.get('redTeam')), inline=True)
		embed.add_field(name=f"💧 Blue ({data.get('blueScore', 0)})", value=team_value('Blue', data.get('blueTeam')), inline=True)
		if any(by_team.values()):
			embed.set_footer(text="Final score")
	await ctx.reply(embed=embed)


async def balance_options(ctx):
	""" Read-only: post Soracle's three balance suggestions for the author's current
		match, so players can copy them into manual picks or ignore them. No menu, no
		reactions, no state change. Shares the embed builder with the match auto-post. """
	match = find(lambda m: m.qc == ctx.qc and ctx.author in m.players, bot.active_matches)
	if match is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("You're not in an active match."))
	if len(match.players) != 12:
		raise bot.Exc.MatchStateError(ctx.qc.gt(
			"Auto-balancing needs exactly 12 players (this match has {n})."
		).format(n=len(match.players)))

	try:
		options = await soracle.fetch_balance([p.id for p in match.players])
	except soracle.UnlinkedError as e:
		raise bot.Exc.NotFoundError(ctx.qc.gt(
			"{players} not linked to a site profile, so teams can't be suggested. An admin can link them."
		).format(players=", ".join(f"<@{i}>" for i in e.unlinked_ids)))
	except soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	await ctx.reply(embed=match.embeds.balance_options(options))


def _kd_lines(players):
	return "\n".join(
		"**{n}.** {name} — **{kd:.2f}** K/D ({k}/{d})".format(
			n=i + 1, name=p['name'], kd=p['kills'] / p['deaths'], k=p['kills'], d=p['deaths']
		) for i, p in enumerate(players)
	)


async def kills_leaderboard(ctx):
	data, players, min_matches = await _monthly_players(ctx)
	# Best K/D. Min-games floor so one big game can't top the board; needs deaths>0.
	ranked = [p for p in players if p.get('deaths') and p.get('matches', 0) >= min_matches]
	top = sorted(ranked, key=lambda p: p['kills'] / p['deaths'], reverse=True)[:5]
	embed = Embed(title=f"Best K/D — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("Not enough games yet for a K/D ranking.")
	else:
		embed.description = _kd_lines(top)
		embed.set_footer(text=f"Min {min_matches} game{'s' if min_matches != 1 else ''} this month")
	await ctx.reply(embed=embed)


async def deaths_leaderboard(ctx):
	data, players, min_matches = await _monthly_players(ctx)
	# Worst K/D, same min-games floor.
	ranked = [p for p in players if p.get('deaths') and p.get('matches', 0) >= min_matches]
	bottom = sorted(ranked, key=lambda p: p['kills'] / p['deaths'])[:5]
	embed = Embed(title=f"Worst K/D — {data.get('month', 'this month')}", colour=Colour(0xe24b4a), url=SITE_URL)
	if not bottom:
		embed.description = ctx.qc.gt("Not enough games yet for a K/D ranking.")
	else:
		embed.description = _kd_lines(bottom)
		embed.set_footer(text=f"Min {min_matches} game{'s' if min_matches != 1 else ''} this month")
	await ctx.reply(embed=embed)


async def flaghold_leaderboard(ctx):
	data, players, _ = await _monthly_players(ctx)
	top = sorted([p for p in players if p.get('flagHoldMs')], key=lambda p: p['flagHoldMs'], reverse=True)[:5]
	embed = Embed(title=f"Most flag hold — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("No flag hold recorded this month yet.")
	else:
		def fmt(ms):
			s = int(ms / 1000)
			return f"{s // 60}m {s % 60}s"
		embed.description = "\n".join(
			f"**{i + 1}.** {p['name']} — **{fmt(p['flagHoldMs'])}**" for i, p in enumerate(top)
		)
	await ctx.reply(embed=embed)


async def returns_leaderboard(ctx):
	# Returns per minute, over returner games only.
	#
	# Dividing returns by every minute played measured which role you were given,
	# not how well you played it: a 6v6 side fields two cappers, a base cleaner, a
	# support and two returners, and the first four aren't trying to return. One
	# player's rate swung 0.09 -> 0.47 per minute between their cap games and the
	# rest. Soracle picks each side's two returners per match off the scoreboard
	# (flag hold, mine grabs) and only those games count.
	try:
		data = await soracle.fetch_returner_rate()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	top = (data.get('top') or [])[:5]
	embed = Embed(title=f"Top returners — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("Not enough returns data this month yet.")
	else:
		embed.description = "\n".join(
			"**{n}.** {name} — **{r:.2f}**/min ({tot} returns in {g} games)".format(
				n=i + 1, name=p['name'], r=p.get('perMinute', 0),
				tot=p.get('returns', 0), g=p.get('games', 0)
			) for i, p in enumerate(top)
		)
		embed.set_footer(text="Counts only games you played as one of your team's two returners. Min {f} such games.".format(
			f=data.get('gameFloor', 0)
		))
	await ctx.reply(embed=embed)


async def caps_leaderboard(ctx):
	# Cap conversion: what share of a player's flag runs ended in a capture.
	#
	# Replaces minutes-of-flag-hold per cap, which players objected to with good
	# reason — it only made sense for capper mains, and it read a long carry as
	# inefficiency whether it ended in a score or a death. A run counts here only
	# once it RESOLVES: you capped, or an enemy returned it off you. Grab-and-
	# /kill resets (how support hands the flag to a runner) resolve neither way
	# and are ignored, instead of counting against you as they did under grabs.
	#
	# Monthly board, rolling over with the rest of the stats. Ordering and the
	# qualifying floor are the site's, computed once in lib/cap-conversion.ts so
	# Discord and the web page can't disagree.
	try:
		data = await soracle.fetch_cap_conversion()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	top = (data.get('top') or [])[:5]
	embed = Embed(title=f"Best cap conversions — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("Not enough capping data yet.")
	else:
		embed.description = "\n".join(
			"**{n}.** {name} — **{pct:.1f}%** ({c} caps / {r} runs)".format(
				n=i + 1, name=p['name'], pct=p.get('conversion', 0),
				c=p.get('captures', 0), r=p.get('carries', 0)
			) for i, p in enumerate(top)
		)
		# The footer is load-bearing: without it the percentage looks like it
		# covers every game ever played, and early in a month it covers a handful.
		m = data.get('matchCount', 0)
		embed.set_footer(text="A run counts once it ends in a cap or a return. {m} match{es} tracked this month · min {f} runs".format(
			m=m, es='' if m == 1 else 'es', f=data.get('carryFloor', 0)
		))
	await ctx.reply(embed=embed)


async def monthly_stats(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	if _suvix_prank(ctx, target):
		await ctx.reply(embed=_suvix_embed())
		return

	try:
		data = await soracle.fetch_player_stats(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	t = data.get('totals') or {}
	profile_url = _profile_url(data.get('name') or get_nick(target))
	embed = Embed(
		title=f"__{data.get('name') or get_nick(target)}__ — {data.get('month', 'this month')}",
		colour=Colour(0x50e3c2),
		url=profile_url
	)
	# Slogan, then the equipped title beneath it (rarity dot + name only). The
	# stat fields already colour-code the embed, so the title just gets a line
	# rather than tinting the whole thing.
	header_lines = []
	if tooltip := data.get('tooltip'):
		header_lines.append(f"*{tooltip}*")
	if title := data.get('title'):
		header_lines.append("{dot} **{t}**".format(dot=RARITY_DOT.get(title.get('rarity'), ''), t=title['title']))
	if header_lines:
		embed.description = "\n".join(header_lines)

	if not data.get('matches'):
		embed.add_field(name="—", value=ctx.qc.gt("No matches recorded this month yet."), inline=False)
	else:
		embed.add_field(
			name=ctx.qc.gt("Matches"),
			value="**{m}** ({w}W / {l}L{d})".format(
				m=data['matches'], w=data.get('wins', 0), l=data.get('losses', 0),
				d=f" / {data['draws']}D" if data.get('draws') else ""
			),
			inline=True
		)
		kills, deaths = t.get('kills', 0), t.get('deaths', 0)
		embed.add_field(name="K/D", value=f"**{kills}/{deaths}** ({kills / (deaths or 1):.2f})", inline=True)
		embed.add_field(name=ctx.qc.gt("Score"), value=f"**{t.get('score', 0)}**", inline=True)
		embed.add_field(name=ctx.qc.gt("Caps"), value=f"**{t.get('captures', 0)}**", inline=True)
		embed.add_field(name=ctx.qc.gt("Returns"), value=f"**{t.get('returns', 0)}**", inline=True)
		embed.add_field(name=ctx.qc.gt("Assists"), value=f"**{t.get('assists', 0)}**", inline=True)
		embed.add_field(name="BC", value=f"**{t.get('baseCleans', 0)}**", inline=True)
		embed.add_field(name=ctx.qc.gt("Flag grabs"), value=f"**{t.get('flagGrabs', 0)}**", inline=True)
		hold_s = int((t.get('flagHoldMs', 0) or 0) / 1000)
		embed.add_field(name=ctx.qc.gt("Flag hold"), value=f"**{hold_s // 60}m {hold_s % 60}s**", inline=True)
		if form := data.get('form'):
			form_emoji = {"W": "🟩", "L": "🟥", "D": "⬜"}
			embed.add_field(
				name=ctx.qc.gt("Form"),
				value="".join(form_emoji.get(r, "⬜") for r in form[-5:]),
				inline=False
			)
	embed.add_field(
		name="—",
		value=ctx.qc.gt("See your full profile at {url}").format(url=profile_url),
		inline=False
	)
	if target.display_avatar:
		embed.set_thumbnail(url=target.display_avatar.url)
	await ctx.reply(embed=embed)


# Rarity → Discord dot emoji + embed accent colour (matches the site's crests).
# oneofone has no true-pink circle emoji in Discord's set, so it gets a star
# instead — fitting, since a one-of-one is the site's own odd one out (octagon,
# not hexagon).
RARITY_DOT = {"common": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "⚪", "oneofone": "⭐"}
RARITY_COLOUR = {
	"common": 0x3ddc84, "rare": 0x2f81f7, "epic": 0xa855f7,
	"legendary": 0xf5c542, "mythic": 0xeaeeff, "oneofone": 0xff2fb9,
}

# Suvix holds the only one-of-one crest in the community and checks on it via
# =achievements/=stats roughly every ten minutes. When he looks himself up he
# gets one of these instead of the page — the Monkey King bit. Rotates so it
# doesn't go stale at his refresh rate. Nothing here is real: his crests and
# stats are untouched on the site, this is purely a Discord-side gag.
SUVIX_ID = 216608375771889666
SUVIX_JABS = (
	"Oooooh, oooh, ah ah ah! 🍌🍌🍌",
	"Your achievements have been forfeit. Goodbye.",
	"The Monkey King has lost his crown.",
	"What are you looking for???",
)


def _suvix_prank(ctx, target):
	""" True when Suvix is looking *himself* up. Keyed on caller and target both,
		so he can still pull up other players, and so everyone else (admins
		included) still sees his real page. """
	return ctx.author.id == SUVIX_ID and target.id == SUVIX_ID


def _suvix_embed():
	""" The whole reply: one jab, no stats, no crests, no profile link. """
	return Embed(description=f"## {choice(SUVIX_JABS)}", colour=Colour(0xf5c542))


def _achievement_line(a):
	""" One "🟡 **Batcher III** — Base cleans in a single match (**100+**)" row.
		`requirement` is the current rank's threshold, sent only for tiered crests
		(untiered conditions already carry their number). Older Soracle deploys
		omit the field, so it degrades to the plain condition. """
	line = "{dot} **{n}** — {c}".format(
		dot=RARITY_DOT.get(a.get('rarity'), '⚪'), n=a['name'], c=a['condition']
	)
	if req := a.get('requirement'):
		line += f" (**{req}**)"
	return line


async def achievements(ctx, player: Member = None):
	""" A player's top unlocked achievements (=achievements). Leads with the rarest
		earned crest as the thumbnail. """
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	if _suvix_prank(ctx, target):
		await ctx.reply(embed=_suvix_embed())
		return

	try:
		data = await soracle.fetch_achievements(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(
			UNLINKED.format(name=get_nick(target), url=SITE_URL)
		)

	name = data.get('name') or get_nick(target)
	profile_url = data.get('profileUrl') or _profile_url(name)
	top = data.get('top') or []

	colour = Colour(RARITY_COLOUR.get(top[0]['rarity'], 0x50e3c2)) if top else Colour(0x50e3c2)
	embed = Embed(title=f"__{name}__ — Achievements", colour=colour, url=profile_url)
	desc_lines = ["**{e}** of **{t}** unlocked".format(
		e=data.get('earnedCount', 0), t=data.get('total', 0)
	)]
	# Equipped title beneath the count (rarity dot + name only), consistent with
	# the other title displays.
	if title := data.get('title'):
		desc_lines.append("{dot} **{t}**".format(dot=RARITY_DOT.get(title.get('rarity'), ''), t=title['title']))
	embed.description = "\n".join(desc_lines)

	if not top:
		embed.add_field(
			name="—",
			value=ctx.qc.gt("No achievements unlocked yet — get grinding!"),
			inline=False
		)
	else:
		embed.add_field(
			name=ctx.qc.gt("Top achievements"),
			value="\n".join(_achievement_line(a) for a in top),
			inline=False
		)
		if img := top[0].get('image'):
			embed.set_thumbnail(url=img)

	embed.add_field(
		name="—",
		value=ctx.qc.gt("See your full profile at {url}").format(url=profile_url),
		inline=False
	)
	await ctx.reply(embed=embed)
