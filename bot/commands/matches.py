__all__ = [
	'show_matches', 'show_teams', 'set_ready', 'sub_me', 'sub_for', 'put',
	'sub_force', 'cap_me', 'cap_for', 'pick', 'report_admin', 'report', 'report_manual',
	'rebalance', 'remove_match_player', 'balance_preview', 'force_start_match'
]

from nextcord import Member
from typing import List
from functools import wraps

from core.config import cfg
from core.utils import get, find

import bot


def author_match(coro):
	@wraps(coro)
	async def wrapper(ctx, *args, **kwargs):
		if (match := find(lambda m: m.qc == ctx.qc and ctx.author in m.players, bot.active_matches)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("You are not in an active match."))
		return await coro(ctx, match, *args, **kwargs)
	return wrapper


async def show_matches(ctx):
	matches = [m for m in bot.active_matches if m.qc.id == ctx.qc.id]
	if len(matches):
		await ctx.reply("\n".join((m.print() for m in matches)))
	else:
		await ctx.reply(ctx.qc.gt("> no active matches"))


@author_match
async def show_teams(ctx, match: bot.Match):
	if match.state == bot.Match.BALANCE and match.balance_menu.options:
		await ctx.reply(embed=match.embeds.balance_preview(match.balance_menu, match.balance_menu.idx))
		return
	if match.state not in [bot.Match.DRAFT, bot.Match.WAITING_REPORT]:
		raise bot.Exc.MatchStateError('Match must be on draft or waiting report state.')
	await match.draft.print(ctx)


@author_match
async def set_ready(ctx, match: bot.Match, is_ready=True):
	await match.check_in.set_ready(ctx, ctx.author, is_ready)


@author_match
async def sub_me(ctx, match: bot.Match):
	await match.draft.sub_me(ctx, ctx.author)


async def sub_for(ctx, player: Member):
	if (match := find(lambda m: m.qc == ctx.qc and player in m.players, bot.active_matches)) is None:
		raise bot.Exc.NotInMatchError(ctx.qc.gt("Specified user is not in a match."))
	await ctx.qc.check_allowed_to_add(ctx, ctx.author, queue=match.queue)
	await match.draft.sub_for(ctx, player, ctx.author)


async def sub_force(ctx, player1: Member, player2: Member):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and player1 in m.players, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Specified user is not in a match."))
	if any((player2 in m.players for m in bot.active_matches)):
		raise bot.Exc.InMatchError(ctx.qc.gt("Specified user is in an active match."))

	await match.draft.sub_for(ctx, player1, player2, force=True)


@author_match
async def cap_me(ctx, match: bot.Match):
	await match.draft.cap_me(ctx, ctx.author)


@author_match
async def cap_for(ctx, match: bot.Match, team_name: str):
	await match.draft.cap_for(ctx, ctx.author, team_name)


@author_match
async def pick(ctx, match: bot.Match, players: List[Member]):
	await match.draft.pick(ctx, ctx.author, players)


@author_match
async def rebalance(ctx, match: bot.Match):
	await match.balance_menu.reopen(ctx, ctx.author)


async def remove_match_player(ctx, player: Member):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and player in m.players, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Specified user is not in a match."))
	await match.remove_player(ctx, player)


async def force_start_match(ctx):
	ctx.check_perms(ctx.Perms.MODERATOR)
	match = find(lambda m: m.qc == ctx.qc and ctx.author in m.players and m.state == bot.Match.DRAFT, bot.active_matches)
	if match is None:
		match = find(lambda m: m.qc == ctx.qc and m.state == bot.Match.DRAFT, bot.active_matches)
	if match is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No drafting match found on this channel."))
	await match.force_start(ctx)


async def balance_preview(ctx, option: int):
	""" Privately (ephemerally) show any balance option to anyone in the channel,
		without changing the public menu. Slash-only — ephemeral needs an interaction. """
	match = find(
		lambda m: m.qc == ctx.qc and m.state == bot.Match.BALANCE and m.balance_menu.options,
		bot.active_matches
	)
	if match is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("There is no balance menu open in this channel right now."))
	idx = option - 1
	if not 0 <= idx < len(match.balance_menu.options):
		raise bot.Exc.SyntaxError(ctx.qc.gt("Pick an option between 1 and {n}.").format(n=len(match.balance_menu.options)))
	await ctx.reply_dm(embed=match.embeds.balance_preview(match.balance_menu, idx))


async def put(ctx, match_id: int, player: Member, team_name: str):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and m.id == match_id, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Could not find match with specified id. Check `/matches`."))
	await match.draft.put(ctx, player, team_name)


async def report_admin(ctx, match_id: int, winner_team=None, draw=False, abort=False):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and m.id == match_id, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Could not find match with specified id. Check `/matches`."))
	if winner_team is None and not draw and not abort:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Please specify a team name or draw."))

	if abort:
		await match.cancel(ctx)
	else:
		await match.report_win(ctx, winner_team, draw)


@author_match
async def report(ctx, match: bot.Match, result):
	if result == 'loss':
		await match.report_loss(ctx, ctx.author, draw_flag=False)
	elif result == 'draw':
		await match.report_loss(ctx, ctx.author, draw_flag=1)
	elif result == 'abort':
		await match.report_loss(ctx, ctx.author, draw_flag=2)
		return
	else:
		raise bot.Exc.ValueError("Invalid result value.")

	# A real result was recorded (loss/draw) — nudge captains to log it on Soracle.
	try:
		await ctx.notice(ctx.qc.gt(
			"📊 Captains: log this game on Soracle → {url}"
		).format(url=cfg.SORACLE_API_URL))
	except Exception:
		pass


async def report_manual(ctx, queue: str, winners: List[Member], losers: List[Member], draw: bool = False):
	""" Report a fake match """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if any((winners.count(p) != 1 or p in losers for p in winners)):
		raise bot.Exc.ValueError(f"Teams can not contain duplicate players.")
	if any((losers.count(p) != 1 or p in winners for p in losers)):
		raise bot.Exc.ValueError(f"Teams can not contain duplicate players.")
	if not len(winners) or not len(losers):
		raise bot.Exc.ValueError(f"Teams can not be empty.")
	await q.fake_ranked_match(ctx, winners, losers, draw=draw)
