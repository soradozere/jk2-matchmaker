__all__ = ['servers_status', 'pug_role_toggle', 'pug_settings']

from nextcord import Embed, Colour
from nextcord.utils import get as dc_get

import bot
from bot import jk2_servers


async def servers_status(ctx):
	results = await jk2_servers.query_all()
	embed = Embed(
		title="JK2 server status",
		colour=Colour(0x50e3c2),
		description="\n".join(jk2_servers.status_lines(results))
	)
	embed.set_footer(text=f"🟢 {jk2_servers.PLAYER_THRESHOLD}+ players · updates live · /pug to get pinged")
	await ctx.reply(embed=embed)


async def pug_settings(ctx):
	await ctx.reply(ctx.qc.gt(
		"I watch {servers} JK2 servers and ping `@{role}` when one reaches **{threshold}+** players "
		"(ironman servers use their ironman count instead). "
		"I won't ping about the same server more than once every **{hours} hours**. "
		"Type {cmd} to join or leave the ping list."
	).format(
		servers=len(jk2_servers.SERVERS),
		role=jk2_servers.PUG_ROLE_NAME,
		threshold=jk2_servers.PLAYER_THRESHOLD,
		hours=jk2_servers.PING_COOLDOWN // 3600,
		cmd="`/pug`"
	))


async def pug_role_toggle(ctx):
	guild = ctx.channel.guild
	role = dc_get(guild.roles, name=jk2_servers.PUG_ROLE_NAME)
	if role is None:
		role = await guild.create_role(
			name=jk2_servers.PUG_ROLE_NAME, mentionable=True, reason="Created by JK2 Matchmaker"
		)

	member = ctx.author
	if role in member.roles:
		await member.remove_roles(role)
		await ctx.success(ctx.qc.gt("Removed, you won't be pinged for PUGs anymore."))
	else:
		await member.add_roles(role)
		await ctx.success(ctx.qc.gt("You're in! You'll get pinged when a server fills up."))
