__all__ = [
	'add', 'remove', 'who', 'add_player', 'remove_player', 'promote', 'start', 'split',
	'reset', 'subscribe', 'server', 'maps', 'set_my_channels', 'my_channels'
]

import time
from random import choice
from nextcord import Member, TextChannel
from core.utils import error_embed, join_and, find, seconds_to_str, resolve_channel
import bot
from bot import player_queue_prefs


def _matching_queues(qc, targets):
	""" Queues on this channel whose name or an alias matches any of `targets`
		(already-lowercased query strings). Shared by add/remove. """
	return [q for q in qc.queues if any(
		t == q.name.lower() or t in (a["alias"].lower() for a in q.cfg.aliases) for t in targets
	)]


def _default_queues(qc):
	""" A channel's own default queue(s) for a bare =j -- active ones first,
		falling back to every default queue if none are active. Shared by add()
		and the cross-channel mirror, so a linked channel picks queues the same
		way a real bare =j typed there would. """
	t_queues = [q for q in qc.queues if len(q.queue) and q.cfg.is_default]
	return t_queues or [q for q in qc.queues if q.cfg.is_default]


async def _mirror_linked_channels(ctx, member, join):
	""" For a bare =j/++ or =l/-- (not a named-queue call), also join/leave
		the player's OTHER linked channels (=set_my_channels) -- e.g. joining
		#comp also joins #casual, and leaving either leaves both, since
		"comp"/"casual" are separate channels here, not queues within one
		channel. Best-effort: a channel that's gone, no longer bot-managed, or
		where the player isn't allowed to add is silently skipped rather than
		failing the whole command -- their own channel already succeeded. """
	linked = await player_queue_prefs.get_linked_channels(member.id)
	if not linked:
		return

	for channel_id in linked:
		if channel_id == ctx.qc.id:
			continue
		if (other_qc := bot.queue_channels.get(channel_id)) is None:
			continue
		system_ctx = bot.SystemContext(other_qc)

		if join:
			try:
				await other_qc.check_allowed_to_add(system_ctx, member)
			except bot.Exc.PubobotException:
				continue
			other_queues = other_qc.queues if len(other_qc.queues) == 1 else _default_queues(other_qc)
			started = False
			for q in other_queues:
				if await q.add_member(system_ctx, member) == bot.Qr.QueueStarted:
					started = True
					break  # match just formed there -- stop, same as a real bare =j would
			if started or any(q.is_added(member) for q in other_queues):
				await other_qc.update_expire(member)
				await system_ctx.notice(other_qc.topic)
		else:
			other_queues = [q for q in other_qc.queues if q.is_added(member)]
			if other_queues:
				for q in other_queues:
					q.pop_members(member)
				if not any(q.is_added(member) for q in other_qc.queues):
					bot.expire.cancel(other_qc, member)
				await system_ctx.notice(other_qc.topic)


async def add(ctx, queues: str = None):
	""" add author to channel queues """
	phrase = await ctx.qc.check_allowed_to_add(ctx, ctx.author)

	targets = queues.lower().split(" ") if queues else []
	bare_join = not len(targets)
	# select the only one queue on the channel
	if bare_join and len(ctx.qc.queues) == 1:
		t_queues = ctx.qc.queues

	# select queues requested by user
	elif len(targets):
		t_queues = _matching_queues(ctx.qc, targets)

	# select active queues or default queues if no active queues
	else:
		t_queues = _default_queues(ctx.qc)

	qr = dict()  # get queue responses
	for q in t_queues:
		qr[q] = await q.add_member(ctx, ctx.author)
		if qr[q] == bot.Qr.QueueStarted:
			await ctx.notice(ctx.qc.topic)
			if bare_join:
				await _mirror_linked_channels(ctx, ctx.author, join=True)
			return

	if len(not_allowed := [q for q in qr.keys() if qr[q] == bot.Qr.NotAllowed]):
		await ctx.error(ctx.qc.gt("You are not allowed to add to {queues} queues.".format(
			queues=join_and([f"**{q.name}**" for q in not_allowed])
		)))

	if bot.Qr.Success in qr.values():
		await ctx.qc.update_expire(ctx.author)
		if phrase:
			await ctx.reply(phrase)
		await ctx.notice(ctx.qc.topic)
	else:  # have to give some response for slash commands
		await ctx.ignore(content=ctx.qc.topic, embed=error_embed(ctx.qc.gt("Action had no effect."), title=None))

	if bare_join:
		await _mirror_linked_channels(ctx, ctx.author, join=True)


async def remove(ctx, queues: str = None):
	""" add author from channel queues """
	targets = queues.lower().split(" ") if queues else []
	bare_leave = not len(targets)

	if bare_leave:
		t_queues = [q for q in ctx.qc.queues if q.is_added(ctx.author)]
	else:
		t_queues = [q for q in _matching_queues(ctx.qc, targets) if q.is_added(ctx.author)]

	if len(t_queues):
		for q in t_queues:
			q.pop_members(ctx.author)

		if not any((q.is_added(ctx.author) for q in ctx.qc.queues)):
			bot.expire.cancel(ctx.qc, ctx.author)

		await ctx.notice(ctx.qc.topic)
	else:
		await ctx.ignore(content=ctx.qc.topic, embed=error_embed(ctx.qc.gt("Action had no effect."), title=None))

	if bare_leave:
		await _mirror_linked_channels(ctx, ctx.author, join=False)


async def who(ctx, queues: str = None):
	""" List added players """
	targets = queues.lower().split(" ") if queues else []

	if len(targets):
		t_queues = [
			q for q in ctx.qc.queues if
			any((t == q.name.lower() or t in (a["alias"].lower() for a in q.cfg.aliases) for t in targets))
		]
	else:
		t_queues = [q for q in ctx.qc.queues if len(q.queue)]

	if not len(t_queues):
		await ctx.reply(f"> {ctx.qc.gt('no players')}")
	else:
		await ctx.reply("\n".join([f"> **{q.name}** ({q.status}) | {q.who}" for q in t_queues]))


async def add_player(ctx, player: Member, queue: str):
	""" Add a player to a queue """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (p := await ctx.get_member(player)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")

	resp = await q.add_member(ctx, p)
	if resp == bot.Qr.Success:
		await ctx.qc.update_expire(p)
		await ctx.reply(ctx.qc.topic)
	elif resp == bot.Qr.QueueStarted:
		await ctx.reply(ctx.qc.topic)
	else:
		await ctx.error(f"Got bad queue response: {resp.__name__}.")


async def remove_player(ctx, player: Member, queues: str = None):
	""" Remove a player from queues """
	ctx.check_perms(ctx.Perms.MODERATOR)

	if (p := await ctx.get_member(player)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	ctx.author = p
	await remove(ctx, queues=queues)


async def promote(ctx, queue: str = None):
	""" Promote a queue """
	if not queue:
		if (q := next(iter(sorted(
			(i for i in ctx.qc.queues if i.length),
			key=lambda i: i.length, reverse=True
		)), None)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("Nothing to promote."))
	else:
		if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("Specified queue not found."))

	now = int(time.time())
	if ctx.qc.cfg.promotion_delay and ctx.qc.cfg.promotion_delay+ctx.qc.last_promote > now:
		raise bot.Exc.PermissionError(ctx.qc.gt("You're promoting too often, please wait `{delay}` until next promote.".format(
			delay=seconds_to_str((ctx.qc.cfg.promotion_delay+ctx.qc.last_promote)-now)
		)))

	await q.promote(ctx)
	ctx.qc.last_promote = now


async def start(ctx, queue: str = None):
	""" Manually start a queue """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	await q.start(ctx)
	await ctx.reply(ctx.qc.topic)


async def split(ctx, queue: str, group_size: int = None, sort_by_rating: bool = False):
	""" Split queue players into X separate matches """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	await q.split(ctx, group_size=group_size, sort_by_rating=sort_by_rating)
	await ctx.reply(ctx.qc.topic)


async def reset(ctx, queue: str = None):
	""" Reset all or specified queue """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue:
		if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
		await q.reset()
	else:
		for q in ctx.qc.queues:
			await q.reset()
	await ctx.reply(ctx.qc.topic)


async def subscribe(ctx, queues: str = None, unsub: bool = False):
	if not queues:
		roles = [ctx.qc.cfg.promotion_role] if ctx.qc.cfg.promotion_role else []
	else:
		queues = queues.split(" ")
		roles = (q.cfg.promotion_role for q in ctx.qc.queues if q.cfg.promotion_role and any(
			(t == q.name.lower() or t in (a["alias"].lower() for a in q.cfg.aliases) for t in queues)
		))

	if unsub:
		roles = [r for r in roles if r in ctx.author.roles]
		if not len(roles):
			raise bot.Exc.ValueError(ctx.qc.gt("No changes to apply."))
		await ctx.author.remove_roles(*roles, reason="subscribe command")
		await ctx.success(ctx.qc.gt("Removed `{count}` roles from you.").format(
			count=len(roles)
		))

	else:
		roles = [r for r in roles if r not in ctx.author.roles]
		if not len(roles):
			raise bot.Exc.ValueError(ctx.qc.gt("No changes to apply."))
		await ctx.author.add_roles(*roles, reason="subscribe command")
		await ctx.success(ctx.qc.gt("Added `{count}` roles to you.").format(
			count=len(roles)
		))


async def server(ctx, queue: str):
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if not q.cfg.server:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Server for **{queue}** is not set.").format(
			queue=q.name
		))
	await ctx.success(q.cfg.server, title=ctx.qc.gt("Server for **{queue}**").format(
		queue=q.name
	))


async def maps(ctx, queue: str, one: bool = False):
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if not len(q.cfg.maps):
		raise bot.Exc.NotFoundError(ctx.qc.gt("No maps is set for **{queue}**.").format(
			queue=q.name
		))

	if one:
		await ctx.success(f"`{choice(q.cfg.maps)['name']}`")
	else:
		await ctx.success(
			", ".join((f"`{i['name']}`" for i in q.cfg.maps)),
			title=ctx.qc.gt("Maps for **{queue}**").format(queue=q.name)
		)


async def set_my_channels(ctx, channel: TextChannel = None, channels: str = None):
	""" Player self-service: links this channel with one or more OTHER queue
		channels (e.g. #comp + #casual) so a bare =j / ++ / =l / -- in any of
		them also joins/leaves the others. Additive -- run it again with a
		different channel to link more. "off" clears the whole group.

		`channel` is the slash path's native single-channel picker; `channels`
		is the message-command path's raw text, which can name several at
		once (space-separated mentions), or the string "off". """
	if channel is None and (channels or "").strip().lower() in ("off", "default", "clear", "none"):
		await player_queue_prefs.clear_linked_channels(ctx.author.id)
		await ctx.success(ctx.qc.gt(
			"Unlinked — `{p}j` / `{p}l` only affect the channel you use them in again."
		).format(p=ctx.qc.cfg.prefix))
		return

	targets, unresolved = ([channel] if channel else []), []
	for token in (channels or "").split(" "):
		if not (token := token.strip()):
			continue
		if (resolved := resolve_channel(ctx.channel.guild, token)) is None:
			unresolved.append(token)
		else:
			targets.append(resolved)

	if not targets:
		raise bot.Exc.SyntaxError(ctx.qc.gt(
			"Usage: {p}set_my_channels __#channel [#channel2 ...]__ (or `off` to unlink everything)"
		).format(p=ctx.qc.cfg.prefix))
	if unresolved:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Not a channel I could find: {names}").format(names=", ".join(unresolved)))

	if len(not_queue_channels := [c for c in targets if bot.queue_channels.get(c.id) is None]):
		raise bot.Exc.SyntaxError(ctx.qc.gt("Not a queue channel: {names}").format(
			names=join_and([c.mention for c in not_queue_channels])
		))

	await player_queue_prefs.add_linked_channels(ctx.author.id, [ctx.qc.id] + [c.id for c in targets])
	linked = await player_queue_prefs.get_linked_channels(ctx.author.id)
	await ctx.success(ctx.qc.gt("`{p}j` / `{p}l` now cover: {names}").format(
		p=ctx.qc.cfg.prefix, names=join_and([f"<#{cid}>" for cid in linked])
	))


async def my_channels(ctx):
	""" Shows the player's current linked-channel group, if any. """
	linked = await player_queue_prefs.get_linked_channels(ctx.author.id)
	if not linked:
		await ctx.reply(ctx.qc.gt(
			"You haven't linked any channels — `{p}j` / `{p}l` only affect the channel you use them in."
		).format(p=ctx.qc.cfg.prefix))
		return

	await ctx.reply(ctx.qc.gt("`{p}j` / `{p}l` currently cover: {names}").format(
		p=ctx.qc.cfg.prefix, names=join_and([f"<#{cid}>" for cid in linked])
	))
