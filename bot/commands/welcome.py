__all__ = ['set_welcome_channel', 'set_welcome_message', 'set_leave_message', 'welcome_preview', 'welcome_config']

from nextcord import TextChannel, Embed, Colour

from core.utils import resolve_channel

import bot


async def set_welcome_channel(ctx, channel: TextChannel = None, channel_name: str = None):
	ctx.check_perms(ctx.Perms.ADMIN)
	target = channel or resolve_channel(ctx.channel.guild, channel_name or "")
	if target is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Channel not found."))
	await bot.welcome.set_channel(ctx.channel.guild.id, target.id)
	await ctx.success(ctx.qc.gt("Welcome/leave messages will post in {channel}.").format(channel=target.mention))


async def set_welcome_message(ctx, message: str):
	ctx.check_perms(ctx.Perms.ADMIN)
	await bot.welcome.set_welcome_message(ctx.channel.guild.id, message)
	await ctx.success(ctx.qc.gt("Welcome message updated."))


async def set_leave_message(ctx, message: str):
	ctx.check_perms(ctx.Perms.ADMIN)
	await bot.welcome.set_leave_message(ctx.channel.guild.id, message)
	await ctx.success(ctx.qc.gt("Leave message updated."))


async def welcome_preview(ctx):
	""" Sends the configured welcome and leave messages for ctx.author, so an
		admin can proof custom text (and the real join-duration formatting)
		without waiting for someone to actually join or leave. """
	ctx.check_perms(ctx.Perms.ADMIN)
	await bot.welcome.on_join(ctx.author)
	await bot.welcome.on_leave(ctx.author, preview=True)


async def welcome_config(ctx):
	""" Shows the current welcome/leave setup — channel and message templates
		(raw, with placeholders, not the rendered text — use =welcome_preview
		for that) — since =set_welcome_* only ever writes, never shows. """
	ctx.check_perms(ctx.Perms.ADMIN)
	cfg = await bot.welcome.get_cfg(ctx.channel.guild.id)
	channel = ctx.channel.guild.get_channel(cfg['channel_id']) if cfg and cfg['channel_id'] else None

	embed = Embed(title="Welcome/leave configuration", colour=Colour(0x7289DA))
	embed.add_field(
		name="Channel",
		value=channel.mention if channel else f"*not set — run `{ctx.qc.cfg.prefix}set_welcome_channel #channel`*",
		inline=False
	)
	embed.add_field(
		name="Welcome message",
		value=(cfg and cfg['welcome_message']) or f"*(default)*\n{bot.welcome.DEFAULT_WELCOME_MESSAGE}",
		inline=False
	)
	embed.add_field(
		name="Leave message",
		value=(cfg and cfg['leave_message']) or f"*(default)*\n{bot.welcome.DEFAULT_LEAVE_MESSAGE}",
		inline=False
	)
	await ctx.reply(embed=embed)
