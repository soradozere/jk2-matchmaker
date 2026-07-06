__all__ = [
	'soracle_info', 'monthly_stats', 'dbs_leaderboard', 'dfa_leaderboard',
	'kills_leaderboard', 'deaths_leaderboard', 'caps_leaderboard', 'potm', 'rivals',
	'grabs_leaderboard', 'bc_leaderboard', 'flaghold_leaderboard', 'returns_leaderboard',
	'streaks_leaderboard', 'redblue', 'nemesis', 'friend', 'duos', 'wrapped', 'last_game_soracle',
	'owneds', 'balance_options'
]

import re
from math import ceil
from datetime import datetime, timezone
from urllib.parse import quote

from nextcord import Member, Embed, Colour

from core.config import cfg
from core.utils import find, get_nick

import bot
from bot import soracle

# Site role names -> community names
ROLE_DISPLAY = {"Cleaner": "BC"}

# Public site for player-facing links (embed titles, profile links). Kept
# separate from SORACLE_API_URL, which stays the API base the bot talks to.
SITE_URL = getattr(cfg, 'PUBLIC_SITE_URL', 'https://jk2ctf.vercel.app')

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

	embed = Embed(title=f"__{data.get('name') or get_nick(target)}__", colour=Colour(0x7289DA))
	if tooltip := data.get('tooltip'):
		embed.description = f"*{tooltip}*"
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


async def _stat_leaderboard(ctx, stat, title, unit=""):
	""" Simple top-5-by-summed-stat board (=dfa, =grabs, ...). """
	try:
		data = await soracle.fetch_stat_leaderboard(stat)
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
	await _stat_leaderboard(ctx, 'dfa_kills', "Top DFA killers")


async def grabs_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'flag_grabs', "Top flag grabbers")


async def bc_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'base_cleaner', "Top base cleaners")


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


async def redblue(ctx):
	try:
		data = await soracle.fetch_monthly_report()
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	rb = data.get('redBlue') or {}
	total = rb.get('total') or 0
	embed = Embed(title=f"🔥 Red vs Blue 💧 — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not total:
		embed.description = ctx.qc.gt("No matches recorded this month yet.")
	else:
		red, blue, draws = rb.get('redWins', 0), rb.get('blueWins', 0), rb.get('draws', 0)
		embed.description = "🔥 Red: **{r}** ({rp}%)\n💧 Blue: **{b}** ({bp}%){d}\nover **{t}** matches".format(
			r=red, rp=int(red * 100 / total), b=blue, bp=int(blue * 100 / total),
			d=f"\n🤝 Draws: **{draws}**" if draws else "", t=total
		)
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
	# Returns per minute played (time_played is in minutes). 30%-of-matches qualifier
	# so a one-game fluke can't top it.
	data, players, min_matches = await _monthly_players(ctx)
	eligible = [
		p for p in players
		if p.get('matches', 0) >= min_matches and p.get('returns') and p.get('timePlayed')
	]
	top = sorted(eligible, key=lambda p: p['returns'] / p['timePlayed'], reverse=True)[:5]
	embed = Embed(title=f"Top returners — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("Not enough returns data this month yet.")
	else:
		embed.description = "\n".join(
			"**{n}.** {name} — **{r:.2f}**/min ({tot} returns)".format(
				n=i + 1, name=p['name'], r=p['returns'] / p['timePlayed'], tot=p['returns']
			) for i, p in enumerate(top)
		)
	await ctx.reply(embed=embed)


async def caps_leaderboard(ctx):
	# Caps efficiency: minutes of flag hold per cap (lower = better). "Most caps per run":
	# regular cappers only (caps >= 30% of the month's max) plus the 30%-of-matches qualifier.
	data, players, min_matches = await _monthly_players(ctx)
	qualified = [p for p in players if p.get('matches', 0) >= min_matches]
	max_caps = max((p.get('captures', 0) for p in qualified), default=0)
	floor = max_caps * 0.3
	eligible = [p for p in qualified if p.get('captures', 0) >= floor and p.get('captures') and p.get('flagHoldMs')]
	top = sorted(eligible, key=lambda p: p['flagHoldMs'] / p['captures'])[:5]
	embed = Embed(title=f"Most caps per run — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=SITE_URL)
	if not top:
		embed.description = ctx.qc.gt("Not enough capping data this month yet.")
	else:
		embed.description = "\n".join(
			"**{n}.** {name} — 1 cap / **{m:.1f} min** ({c} caps)".format(
				n=i + 1, name=p['name'], m=p['flagHoldMs'] / 60000 / p['captures'], c=p['captures']
			) for i, p in enumerate(top)
		)
	await ctx.reply(embed=embed)


async def monthly_stats(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

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
	if tooltip := data.get('tooltip'):
		embed.description = f"*{tooltip}*"

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


async def owneds(ctx, player: Member = None):
	""" =owneds — two top-3 kill-matchup boards for a player this month: the
		opponents they're out-fragging across shared stat-tracked games, and the
		opponents out-fragging them. Ranked by total kill differential. """
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	try:
		data = await soracle.fetch_owneds(target.id)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))
	if data is None:
		raise bot.Exc.NotFoundError(UNLINKED.format(name=get_nick(target), url=SITE_URL))

	name = data.get('name') or get_nick(target)
	embed = Embed(title=f"Owneds — {name} ({data.get('month', 'this month')})", colour=Colour(0x9b59b6), url=_profile_url(name))

	def _lines(rows, sign):
		return "\n".join(
			"**{i}.** **{opp}** — {sign}{diff} kills (**{mine}–{theirs}** over {g} games)".format(
				i=i + 1, opp=r['name'], sign=sign, diff=abs(r['diff']),
				mine=r['myKills'], theirs=r['theirKills'], g=r['games']
			) for i, r in enumerate(rows)
		)

	owned, owned_by = data.get('owned') or [], data.get('ownedBy') or []
	if not owned and not owned_by:
		embed.description = ctx.qc.gt("No kill matchups yet this month — play a few more stat-tracked games.")
	else:
		embed.add_field(
			name="😈 Owning",
			value=_lines(owned, "+") or ctx.qc.gt("No one yet — get fragging."),
			inline=False
		)
		embed.add_field(
			name="💀 Owned by",
			value=_lines(owned_by, "−") or ctx.qc.gt("No one — untouchable."),
			inline=False
		)
		embed.set_footer(text="Kill differential across this month's shared stat-tracked games (min 2 together).")
	await ctx.reply(embed=embed)
