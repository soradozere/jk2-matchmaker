__all__ = [
	'show_matches', 'show_teams', 'set_ready', 'sub_me', 'sub_for', 'put',
	'sub_force', 'cap_me', 'cap_for', 'pick', 'report_admin', 'report', 'report_manual',
	'rebalance', 'manual', 'remove_match_player', 'force_start_match', 'show_captain_combos'
]

from nextcord import Member, DiscordException, Embed, Colour
from typing import List
from functools import wraps

from core.utils import get, find

import bot
from bot import soracle
from bot import captain_combos


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
	if match.state not in [bot.Match.DRAFT, bot.Match.WAITING_REPORT]:
		raise bot.Exc.MatchStateError('Match must be on draft or waiting report state.')
	if match.state == bot.Match.WAITING_REPORT:
		# Teams are locked in past this point -- show the same styled roster the
		# "has started" post used, not the draft-stage embed (=teams was reverting
		# to the old plain-nick style after the bot had already picked).
		try:
			await ctx.notice(embed=match.embeds.final_message())
		except DiscordException:
			pass
	else:
		await match.draft.print(ctx)


async def show_captain_combos(ctx):
	""" Reference list for the "captain combos" pick_captains mode -- doesn't
		need an active match, just prints what's in captain_combos.py so admins/
		players can check it without digging up the source file. """
	perfect = [(a, b) for a, b, is_perfect, _ in captain_combos.COMBOS if is_perfect]
	conditional = [(a, b, fp) for a, b, is_perfect, fp in captain_combos.COMBOS if not is_perfect]

	embed = Embed(
		title="Captain combos",
		colour=Colour(0x50e3c2),
		description=(
			"Used when `pick_captains` is set to `captain combos`. **Perfect Match** pairs are "
			"tried first (random pick if several fit, random first pick between the two). "
			"**Conditional** pairs are only used when no Perfect Match is available in the queue, "
			"and the named player gets first pick."
		)
	)
	embed.add_field(
		name=f"⚖️ Perfect Match ({len(perfect)})",
		value="\n".join(f"{a} vs {b}" for a, b in perfect) or ctx.qc.gt("None set."),
		inline=False
	)
	embed.add_field(
		name=f"🎯 Conditional ({len(conditional)})",
		value="\n".join(f"{a} vs {b} — **{fp}** gets first pick" for a, b, fp in conditional) or ctx.qc.gt("None set."),
		inline=False
	)
	await ctx.reply(embed=embed)


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
	await match.auto_balance.rebalance(ctx, ctx.author)


async def manual(ctx):
	""" =manual: admin-only, so it isn't restricted to captains or match players
		(mirrors force_start_match's lookup: prefer a match the admin is in, else any
		match on the channel). """
	ctx.check_perms(ctx.Perms.MODERATOR)
	match = find(lambda m: m.qc == ctx.qc and ctx.author in m.players, bot.active_matches)
	if match is None:
		match = find(lambda m: m.qc == ctx.qc, bot.active_matches)
	if match is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("No active match found on this channel."))
	await match.auto_balance.go_manual(ctx, ctx.author)


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

	# A real result was recorded (loss/draw) — nudge captains to log it on the site.
	try:
		await ctx.notice(ctx.qc.gt(
			"📊 Captains: log this game → {url}"
		).format(url=soracle.site_url()))
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
