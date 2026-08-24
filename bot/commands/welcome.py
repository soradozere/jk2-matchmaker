__all__ = ['set_welcome_channel', 'set_welcome_message', 'set_leave_message', 'welcome_preview']

from nextcord import TextChannel

from core.utils import find

import bot


def _resolve_channel(guild, arg):
	if arg.startswith('<#') and arg.endswith('>'):
		return guild.get_channel(int(arg[2:-1]))
	return find(lambda c: c.name.lower() == arg.lstrip('#').lower(), guild.text_channels)


async def set_welcome_channel(ctx, channel: TextChannel = None, channel_name: str = None):
	ctx.check_perms(ctx.Perms.ADMIN)
	target = channel or _resolve_channel(ctx.channel.guild, channel_name or "")
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
	await bot.welcome.on_leave(ctx.author)
