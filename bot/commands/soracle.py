__all__ = ['soracle_info', 'monthly_stats', 'dbs_leaderboard']

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


async def dbs_leaderboard(ctx):
	try:
		data = await soracle.fetch_stat_leaderboard('dbs_kills')
	except bot.soracle.SoracleError as e:
		raise bot.Exc.NotFoundError(str(e))

	top = data.get('top') or []
	embed = Embed(
		title=f"Top DBS killers — {data.get('month', 'this month')}",
		colour=Colour(0x50e3c2),
		url=cfg.SORACLE_API_URL
	)
	if not top:
		embed.description = ctx.qc.gt("No DBS kills recorded this month yet.")
	else:
		embed.description = "\n".join(
			f"**{n + 1}.** {r['name']} — **{r['value']}**" for n, r in enumerate(top)
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
