__all__ = ['set_youtube_channel', 'set_youtube_enabled', 'youtube_config']

from nextcord import TextChannel, Embed, Colour

from core.utils import resolve_channel

import bot


async def set_youtube_channel(ctx, channel: TextChannel = None, channel_name: str = None):
	ctx.check_perms(ctx.Perms.ADMIN)
	target = channel or resolve_channel(ctx.channel.guild, channel_name or "")
	if target is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Channel not found."))
	await bot.youtube.set_channel(ctx.channel.guild.id, target.id)
	await ctx.success(ctx.qc.gt("New JK2 CTF YouTube uploads will post in {channel}.").format(channel=target.mention))


async def set_youtube_enabled(ctx, state=None):
	ctx.check_perms(ctx.Perms.ADMIN)
	if isinstance(state, bool):
		enabled = state
	elif isinstance(state, str) and state.lower() in ('on', 'off'):
		enabled = state.lower() == 'on'
	else:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Usage: `{prefix}set_youtube_enabled on|off`").format(
			prefix=ctx.qc.cfg.prefix
		))
	await bot.youtube.set_enabled(ctx.channel.guild.id, enabled)
	await ctx.success(ctx.qc.gt("YouTube upload announcements are now **{state}**.").format(
		state="on" if enabled else "off"
	))


async def youtube_config(ctx):
	ctx.check_perms(ctx.Perms.ADMIN)
	cfg = await bot.youtube.get_cfg(ctx.channel.guild.id)
	channel = ctx.channel.guild.get_channel(cfg['channel_id']) if cfg and cfg['channel_id'] else None

	embed = Embed(title="YouTube upload watcher", colour=Colour(0x7289DA))
	embed.add_field(name="Enabled", value="on" if cfg and cfg['enabled'] else "off", inline=True)
	embed.add_field(
		name="Channel",
		value=channel.mention if channel else f"*not set — run `{ctx.qc.cfg.prefix}set_youtube_channel #channel`*",
		inline=True
	)
	embed.add_field(
		name="Last posted video",
		value=f"https://www.youtube.com/watch?v={cfg['last_video_id']}" if cfg and cfg['last_video_id'] else "*none yet*",
		inline=False
	)
	await ctx.reply(embed=embed)
