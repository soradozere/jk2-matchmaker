__all__ = ['soracle_info']

import asyncio
import aiohttp
from nextcord import Member, Embed, Colour

from core.config import cfg
from core.utils import get_nick

import bot


async def soracle_info(ctx, player: Member = None):
	target = ctx.author if not player else await ctx.get_member(player)
	if not target:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	url = f"{cfg.SORACLE_API_URL}/api/bot/player/by-discord/{target.id}"
	headers = {'Authorization': f"Bearer {cfg.SORACLE_API_SECRET}"}

	try:
		timeout = aiohttp.ClientTimeout(total=5)
		async with aiohttp.ClientSession(timeout=timeout) as session:
			async with session.get(url, headers=headers) as resp:
				status = resp.status
				data = await resp.json(content_type=None) if status == 200 else None
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise bot.Exc.NotFoundError("Could not reach Soracle, please try again later.")

	if status == 404:
		raise bot.Exc.NotFoundError(
			f"**{get_nick(target)}** is not linked to a Soracle player. An admin can link them on Soracle."
		)
	if status != 200 or data is None:
		raise bot.Exc.NotFoundError(f"Soracle returned an unexpected response (HTTP {status}).")

	embed = Embed(title=f"__{data.get('name') or get_nick(target)}__", colour=Colour(0x7289DA))
	if tooltip := data.get('tooltip'):
		embed.description = f"*{tooltip}*"
	embed.add_field(name="Tier", value=f"**{data.get('tier', '?')}**", inline=True)
	roles = data.get('roles') or {}
	if isinstance(roles, dict):
		roles_str = "\n".join(f"{name}: **{score}**" for name, score in roles.items())
	else:
		roles_str = ", ".join(map(str, roles))
	embed.add_field(name="Roles", value=roles_str or "—", inline=True)
	if target.display_avatar:
		embed.set_thumbnail(url=target.display_avatar.url)
	embed.set_footer(text="Soracle")
	await ctx.reply(embed=embed)
