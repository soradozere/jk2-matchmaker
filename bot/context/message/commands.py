import traceback
import re
from typing import Callable

from core.client import dc
from core.config import cfg
from core.console import log
from core.utils import get_nick, parse_duration

import bot

from . import MessageContext

_commands = {}


def message_command(*aliases: str):

	def decorator(coro: Callable):
		for alias in aliases:
			_commands[alias] = coro

		async def wrapper(*args, **kwargs):
			return await coro(*args, **kwargs)
		return wrapper

	return decorator


def soracle_command(*aliases: str):
	""" Like message_command, but only registers the command when the Soracle
		integration is enabled. With SORACLE_ENABLED off these commands are never
		added, so typing them does nothing — the bot runs as plain manual picking. """
	if not getattr(cfg, 'SORACLE_ENABLED', True):
		return lambda coro: coro
	return message_command(*aliases)


@dc.event
async def on_message(message):
	if not message.content or message.content == "":
		return

	if (qc := bot.queue_channels.get(message.channel.id)) is None:
		return

	# special commands
	if re.match(r"^\+..", message.content):
		f, args = _commands.get('add'), [message.content[1:]]
	elif re.match(r"^-..", message.content):
		f, args = _commands.get('remove'), [message.content[1:]]
	elif message.content == "++":
		f, args = _commands.get('add'), []
	elif message.content == "--":
		f, args = _commands.get('remove'), []

	elif message.content[0] == qc.cfg.prefix:
		cmd_args = message.content[1:].split(' ', 1)
		f = _commands.get(cmd_args[0])
		args = cmd_args[1:]

	else:
		return

	if f is not None:
		ctx = MessageContext(qc, message)
		log.command("{} | #{} | {}: {}".format(
			ctx.channel.guild.name, ctx.channel.name, get_nick(message.author), message.content
		))

		if not bot.bot_ready:
			await ctx.error("Bot is under connection, please try agian later...", title="Error")
			return

		try:
			await f(ctx, *args)
		except bot.Exc.PubobotException as e:
			await ctx.error(str(e), title=e.__class__.__name__)
		except Exception as e:
			tb = traceback.format_exc()
			# Surface the traceback tail in Discord so crashes can be debugged without
			# digging through hosting logs. The triggering owner sees it inline;
			# otherwise the owner is DM'd it (whoever set off the crash).
			detail = str(e)
			if ctx.author.id == cfg.DC_OWNER_ID:
				detail = f"{str(e)}\n```\n{tb[-1500:]}\n```"
			await ctx.error(detail, title="RuntimeError")
			if ctx.author.id != cfg.DC_OWNER_ID:
				try:
					owner = dc.get_user(cfg.DC_OWNER_ID) or await dc.fetch_user(cfg.DC_OWNER_ID)
					if owner:
						await owner.send(
							f"⚠️ `{message.content}` by {ctx.author} crashed:\n```\n{tb[-1800:]}\n```"
						)
				except Exception:
					pass
			log.error("\n".join([
				f"Error processing a text message command.",
				f"QC: {ctx.channel.guild.name}>#{ctx.channel.name} ({qc.id}).",
				f"Member: {ctx.author} ({ctx.author.id}).",
				f"Content: `{message.content}`.",
				f"Exception: {str(e)}. Traceback:\n{tb}=========="
			]))


@message_command('add', 'j')
async def _add(ctx: MessageContext, args: str = None):
	await bot.commands.add(ctx, queues=args)


@message_command('remove', 'l')
async def _remove(ctx: MessageContext, args: str = None):
	await bot.commands.remove(ctx, queues=args)


@message_command('who')
async def _remove(ctx: MessageContext, args: str = None):
	await bot.commands.who(ctx, queues=args)


@message_command('queues')
async def _queues(ctx: MessageContext, args: str = None):
	await bot.commands.show_queues(ctx)


@message_command('help', 'commands')
async def _commands_help(ctx: MessageContext, args: str = None):
	await bot.commands.commands_help(ctx)


@message_command('teams')
async def _teams(ctx: MessageContext, args: str = None):
	await bot.commands.show_teams(ctx)


@message_command('tz')
async def _tz(ctx: MessageContext, args: str = None):
	await bot.commands.tz(ctx)


@message_command('set_welcome_channel')
async def _set_welcome_channel(ctx: MessageContext, args: str = None):
	await bot.commands.set_welcome_channel(ctx, channel_name=args)


@message_command('set_welcome_message')
async def _set_welcome_message(ctx: MessageContext, args: str = None):
	await bot.commands.set_welcome_message(ctx, message=args)


@message_command('set_leave_message')
async def _set_leave_message(ctx: MessageContext, args: str = None):
	await bot.commands.set_leave_message(ctx, message=args)


@message_command('welcome_preview')
async def _welcome_preview(ctx: MessageContext, args: str = None):
	await bot.commands.welcome_preview(ctx)


@message_command('welcome_config')
async def _welcome_config(ctx: MessageContext, args: str = None):
	await bot.commands.welcome_config(ctx)


@message_command('urban')
async def _urban(ctx: MessageContext, args: str = None):
	await bot.commands.urban(ctx, term=args)


@message_command('subme')
async def _sub_me(ctx: MessageContext, args: str = None):
	await bot.commands.sub_me(ctx)


@message_command('subfor')
async def _sub_for(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}sub_for __@player__")
	elif (player := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	await bot.commands.sub_for(ctx, player=player)


@message_command('capme')
async def _cap_me(ctx: MessageContext, args: str = None):
	await bot.commands.cap_me(ctx)


@message_command('capfor')
async def _cap_for(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}capfor __team__")

	await bot.commands.cap_for(ctx, team_name=args)


@message_command('pick', 'p')
async def _pick(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}pick __player__")

	members = [await ctx.get_member(i.strip()) for i in args.strip().split(" ")]
	if None in members:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))

	await bot.commands.pick(ctx, players=members)


@message_command('report_loss', 'rl')
async def _rl(ctx: MessageContext, args: str = None):
	await bot.commands.report(ctx, result='loss')


# Draw / abort are intentionally not player commands (no ties; aborting is
# admin-only via /match report to avoid accidental cancels).


@message_command('expire')
async def _expire(ctx: MessageContext, args: str = None):
	duration = None
	if args:
		try:
			duration = parse_duration(args)
		except ValueError:
			raise bot.Exc.SyntaxError(ctx.qc.gt("Invalid duration format. Syntax: 3h2m1s or 03:02:01."))
	await bot.commands.expire(ctx, duration=duration)


@message_command('rank')
async def _rank(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.rank(ctx, player=None)
		return
	member = await ctx.get_member(args)
	await bot.commands.rank(ctx, player=member)


@message_command('servers')
async def _servers(ctx: MessageContext, args: str = None):
	await bot.commands.servers_status(ctx)


@message_command('pug')
async def _pug(ctx: MessageContext, args: str = None):
	await bot.commands.pug_role_toggle(ctx)


@message_command('pug_settings')
async def _pug_settings(ctx: MessageContext, args: str = None):
	await bot.commands.pug_settings(ctx)


@message_command('start_match', 'startmatch')
async def _force_start_match(ctx: MessageContext, args: str = None):
	await bot.commands.force_start_match(ctx)


@message_command('remove_match_player', 'rmp')
async def _remove_match_player(ctx: MessageContext, args: str = ""):
	if not args or (member := await ctx.get_member(args.strip())) is None:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}remove_match_player __@player__")
	await bot.commands.remove_match_player(ctx, player=member)


@soracle_command('rebalance')
async def _rebalance(ctx: MessageContext, args: str = None):
	await bot.commands.rebalance(ctx)


@soracle_command('manual')
async def _manual(ctx: MessageContext, args: str = None):
	await bot.commands.manual(ctx)


@soracle_command('options', 'opts')
async def _options(ctx: MessageContext, args: str = None):
	await bot.commands.balance_options(ctx)


@soracle_command('stats')
async def _monthly_stats(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.monthly_stats(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.monthly_stats(ctx, player=member)


@soracle_command('achievements', 'achs')
async def _achievements(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.achievements(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.achievements(ctx, player=member)


@soracle_command('dbs')
async def _dbs(ctx: MessageContext, args: str = None):
	await bot.commands.dbs_leaderboard(ctx)


@soracle_command('dfa')
async def _dfa(ctx: MessageContext, args: str = None):
	await bot.commands.dfa_leaderboard(ctx)


@soracle_command('kills')
async def _kills(ctx: MessageContext, args: str = None):
	await bot.commands.kills_leaderboard(ctx)


@soracle_command('deaths')
async def _deaths(ctx: MessageContext, args: str = None):
	await bot.commands.deaths_leaderboard(ctx)


@soracle_command('caps')
async def _caps(ctx: MessageContext, args: str = None):
	await bot.commands.caps_leaderboard(ctx)


@soracle_command('potm')
async def _potm(ctx: MessageContext, args: str = None):
	await bot.commands.potm(ctx)


@soracle_command('rivals')
async def _rivals(ctx: MessageContext, args: str = None):
	await bot.commands.rivals(ctx)


@soracle_command('duos')
async def _duos(ctx: MessageContext, args: str = None):
	await bot.commands.duos(ctx)


@soracle_command('grabs')
async def _grabs(ctx: MessageContext, args: str = None):
	await bot.commands.grabs_leaderboard(ctx)


@soracle_command('bc')
async def _bc(ctx: MessageContext, args: str = None):
	await bot.commands.bc_leaderboard(ctx)


@soracle_command('doom')
async def _doom(ctx: MessageContext, args: str = None):
	await bot.commands.doom_leaderboard(ctx)


@soracle_command('flaghold')
async def _flaghold(ctx: MessageContext, args: str = None):
	await bot.commands.flaghold_leaderboard(ctx)


@soracle_command('returns')
async def _returns(ctx: MessageContext, args: str = None):
	await bot.commands.returns_leaderboard(ctx)


@soracle_command('streak', 'streaks')
async def _streak(ctx: MessageContext, args: str = None):
	await bot.commands.streaks_leaderboard(ctx)


@soracle_command('redblue')
async def _redblue(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.redblue(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.redblue(ctx, player=member)


@soracle_command('nemesis')
async def _nemesis(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.nemesis(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.nemesis(ctx, player=member)


@soracle_command('friend')
async def _friend(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.friend(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.friend(ctx, player=member)


@soracle_command('curse')
async def _curse(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.curse(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.curse(ctx, player=member)


@soracle_command('wrapped')
async def _wrapped(ctx: MessageContext, args: str = None):
	await bot.commands.wrapped(ctx)


@soracle_command('tier')
async def _soracle(ctx: MessageContext, args: str = None):
	if not args:
		await bot.commands.soracle_info(ctx, player=None)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.soracle_info(ctx, player=member)


@message_command('leaderboard', 'lb')
async def _leaderboard(ctx: MessageContext, args: str = None):
	page = int(args) if args else None
	await bot.commands.leaderboard(ctx, page=page)


@soracle_command('lastgame', 'lg')
async def _lastgame(ctx: MessageContext, args: str = None):
	# =lg = last match on Soracle; =lg @player = that player's last game.
	# The vanilla pubobot view lives on =lastgame_vanilla / =lgv.
	if not args:
		await bot.commands.last_game_soracle(ctx)
		return
	if (member := await ctx.get_member(args)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	await bot.commands.last_game_soracle(ctx, player=member)


@message_command('lastgame_vanilla', 'lgv')
async def _lastgame_vanilla(ctx: MessageContext, args: str = None):
	""" Guess parameter name on the supplied value type :peka5: """
	if not args:
		await bot.commands.last_game(ctx)
	elif args.isdigit():
		await bot.commands.last_game(ctx, match_id=int(args))
	elif (member := await ctx.get_member(args)) is not None:
		await bot.commands.last_game(ctx, player=member)
	else:
		await bot.commands.last_game(ctx, queue=args)


@message_command('cancel_match')
async def _cancel_match(ctx: MessageContext, args: str = None):
	if not args or not args.isdigit():
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}cancel_match __match_id__")
	await bot.commands.report_admin(ctx, match_id=int(args), abort=True)


@message_command('promote')
async def _promote(ctx: MessageContext, args: str = None):
	await bot.commands.promote(ctx, args)


@message_command('set_channel_cfg')
async def _set_qc_cfg(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}set_channel_cfg __json__")
	await bot.commands.set_qc_cfg(ctx, args.strip())


@message_command('set_queue_cfg')
async def _set_queue_cfg(ctx: MessageContext, args: str = ""):
	if len(args := args.split(" ", maxsplit=1)) != 2:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}set_queue_cfg __queue__ __json__")
	await bot.commands.set_queue_cfg(ctx, args[0], args[1].strip())


@message_command('stats_reset_player')
async def _stats_reset_player(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}stats_reset_player __@player__")

	await bot.commands.stats_reset_player(ctx, player=args)


@message_command('stats_replace_player')
async def _stats_replace_player(ctx: MessageContext, args: str = ""):
	if len(args := args.split(" ")) != 2:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}stats_replace_player __@player1__ __@player2__")

	await bot.commands.stats_replace_player(ctx, player1=args[0], player2=args[1])


@message_command('rating_hide_player')
async def _rating_hide(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}rating_hide __@player__")

	await bot.commands.rating_hide(ctx, player=args)


@message_command('rating_unhide_player')
async def _rating_unhide(ctx: MessageContext, args: str = None):
	if not args:
		raise bot.Exc.SyntaxError(f"Usage: {ctx.qc.cfg.prefix}rating_unhide_player __@player__")

	await bot.commands.rating_hide(ctx, player=args, hide=False)
