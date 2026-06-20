__all__ = [
	'soracle_info', 'monthly_stats', 'dbs_leaderboard', 'dfa_leaderboard',
	'kills_leaderboard', 'caps_leaderboard', 'potm', 'rivals'
]

from math import ceil

from nextcord import Member, Embed, Colour

from core.config import cfg
from core.utils import get_nick

import bot
from bot import soracle

# Soracle role names -> community names
ROLE_DISPLAY = {"Cleaner": "BC"}


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
			f"**{get_nick(target)}** is not linked to a Soracle player. An admin can link them on Soracle."
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
	embed.set_footer(text="Soracle")
	await ctx.reply(embed=embed)


async def _stat_leaderboard(ctx, stat, title, unit=""):
	""" Simple top-5-by-summed-stat board (=dbs, =dfa). """
	try:
		data = await soracle.fetch_stat_leaderboard(stat)
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	top = data.get('top') or []
	embed = Embed(title=f"{title} — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=cfg.SORACLE_API_URL)
	if not top:
		embed.description = ctx.qc.gt("Nothing recorded this month yet.")
	else:
		embed.description = "\n".join(
			f"**{n + 1}.** {r['name']} — **{r['value']}**{unit}" for n, r in enumerate(top)
		)
	await ctx.reply(embed=embed)


async def dbs_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'dbs_kills', "Top DBS killers")


async def dfa_leaderboard(ctx):
	await _stat_leaderboard(ctx, 'dfa_kills', "Top DFA killers")


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
		url=cfg.SORACLE_API_URL
	)
	if not star:
		embed.description = ctx.qc.gt("No qualifying player yet this month.")
	else:
		games = star.get('wins', 0) + star.get('losses', 0)
		winrate = int(star['wins'] * 100 / games) if games else 0
		embed.description = "## {name}\n**{w}W / {l}L** ({wr}% winrate) over {m} games\nUpset-weighted rating: **{s}**".format(
			name=star['name'], w=star.get('wins', 0), l=star.get('losses', 0),
			wr=winrate, m=star.get('matches', 0), s=star.get('avgScore', 0)
		)
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
		url=cfg.SORACLE_API_URL
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
	await ctx.reply(embed=embed)


async def kills_leaderboard(ctx):
	data, players, _ = await _monthly_players(ctx)
	top = sorted([p for p in players if p.get('kills')], key=lambda p: p['kills'], reverse=True)[:5]
	embed = Embed(title=f"Top fraggers — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=cfg.SORACLE_API_URL)
	if not top:
		embed.description = ctx.qc.gt("No kills recorded this month yet.")
	else:
		embed.description = "\n".join(
			"**{n}.** {name} — **{k}** kills (K/D {kd})".format(
				n=i + 1, name=p['name'], k=p['kills'],
				kd=f"{p['kills'] / p['deaths']:.2f}" if p.get('deaths') else "∞"
			) for i, p in enumerate(top)
		)
	await ctx.reply(embed=embed)


async def caps_leaderboard(ctx):
	# Caps efficiency: minutes of flag hold per cap (lower = better). Matches Soracle's
	# "Most Caps per Run": regular cappers only (caps >= 40% of the month's max) plus the
	# 30%-of-matches qualifier.
	data, players, min_matches = await _monthly_players(ctx)
	qualified = [p for p in players if p.get('matches', 0) >= min_matches]
	max_caps = max((p.get('captures', 0) for p in qualified), default=0)
	floor = max_caps * 0.4
	eligible = [p for p in qualified if p.get('captures', 0) >= floor and p.get('captures') and p.get('flagHoldMs')]
	top = sorted(eligible, key=lambda p: p['flagHoldMs'] / p['captures'])[:5]
	embed = Embed(title=f"Most caps per run — {data.get('month', 'this month')}", colour=Colour(0x50e3c2), url=cfg.SORACLE_API_URL)
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
			f"**{get_nick(target)}** is not linked to a Soracle player. An admin can link them on Soracle."
		)

	t = data.get('totals') or {}
	embed = Embed(
		title=f"__{data.get('name') or get_nick(target)}__ — {data.get('month', 'this month')}",
		colour=Colour(0x50e3c2),
		url=cfg.SORACLE_API_URL
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
		value=ctx.qc.gt("See the full highlights of the month at {url}").format(url=cfg.SORACLE_API_URL),
		inline=False
	)
	if target.display_avatar:
		embed.set_thumbnail(url=target.display_avatar.url)
	embed.set_footer(text="Soracle")
	await ctx.reply(embed=embed)
