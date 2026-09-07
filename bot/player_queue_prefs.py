# -*- coding: utf-8 -*-
""" Per-player default queue selection. Lets a player set which queues a bare
	=j / ++ (no queue names given) should add them to on a given channel --
	e.g. both "comp" and "casual" every time -- instead of just the channel's
	own default queue(s). Off by default: with nothing set, =j behaves
	exactly as it always has (bot/commands/queues.py:add falls back to the
	channel's default queues when this returns None or resolves to nothing).

	Deliberately does not change =l / -- (remove): a bare removal already
	pops the author from every queue they're currently added to, regardless
	of how they got added, so multi-queue joins are already cleanly undone. """

from core.database import db

db.ensure_table(dict(
	tname="player_default_queues",
	columns=[
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="queues", ctype=db.types.str),  # comma-separated lowercase queue names
	],
	primary_keys=["channel_id", "user_id"]
))


async def get_default(channel_id, user_id):
	""" Returns a list of lowercase queue names the player wants =j to use on
		this channel, or None if they haven't set one. """
	row = await db.select_one(
		['queues'], 'player_default_queues', where=dict(channel_id=channel_id, user_id=user_id)
	)
	if not row or not row['queues']:
		return None
	return [q for q in row['queues'].split(",") if q]


async def set_default(channel_id, user_id, queue_names):
	""" queue_names: list of (lowercase, already-resolved) queue names. An
		empty list clears the preference, reverting to the channel default. """
	value = ",".join(sorted(set(queue_names)))
	if await db.select_one(
		['channel_id'], 'player_default_queues', where=dict(channel_id=channel_id, user_id=user_id)
	) is None:
		await db.insert('player_default_queues', dict(channel_id=channel_id, user_id=user_id, queues=value))
	else:
		await db.update(
			'player_default_queues', dict(queues=value), keys=dict(channel_id=channel_id, user_id=user_id)
		)
