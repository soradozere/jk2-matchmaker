# -*- coding: utf-8 -*-
""" Match-count bans: a banned player is blocked from adding to queues on ONE
	channel (not guild-wide) until a set number of matches have started on
	that channel -- "a match" means any match starting there, whether or not
	the banned player would have been in it. No time component at all: a
	channel that's quiet for a day makes the ban last a day; a busy one clears
	it in an hour. That's deliberate -- tick_games() is called once per match
	start (bot/match/match.py), not on a timer. """

import time
from random import choice
from core.database import db
from core.utils import get_nick

db.ensure_table(dict(
	tname="noadds",
	columns=[
		dict(cname="id", ctype=db.types.int, autoincrement=True),
		dict(cname="guild_id", ctype=db.types.int),
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="name", ctype=db.types.str),
		dict(cname="is_active", ctype=db.types.bool, default=1),
		dict(cname="at", ctype=db.types.int),
		dict(cname="games_remaining", ctype=db.types.int),
		dict(cname="reason", ctype=db.types.text),
		dict(cname="by", ctype=db.types.str),
		dict(cname="released_by", ctype=db.types.str)
	],
	primary_keys=["id"]
))

db.ensure_table(dict(
	tname="qc_phrases",
	columns=[
		dict(cname="channel_id", ctype=db.types.int),
		dict(cname="user_id", ctype=db.types.int),
		dict(cname="phrase", ctype=db.types.text),
	]
))


class NoAdds:

	MIN_GAMES = 1
	MAX_GAMES = 5

	@staticmethod
	async def get_user(ctx, member):
		""" returns [games_left, phrase]. games_left is 0 if not banned on
			this channel (a ban on a different channel doesn't count). """
		m_noadd = await db.select_one(
			['games_remaining'], 'noadds', where=dict(channel_id=ctx.channel.id, user_id=member.id, is_active=1)
		)
		games_left = max(0, m_noadd['games_remaining']) if m_noadd else 0
		phrases = await db.select(['phrase'], 'qc_phrases', where=dict(channel_id=ctx.channel.id, user_id=member.id))

		return [games_left, choice(phrases)['phrase'] if len(phrases) else None]

	@staticmethod
	async def phrases_add(ctx, member, phrase):
		await db.insert('qc_phrases', dict(channel_id=ctx.channel.id, user_id=member.id, phrase=phrase))

	@staticmethod
	async def phrases_clear(ctx, member=None):
		if member:
			await db.delete('qc_phrases', where=dict(channel_id=ctx.channel.id, user_id=member.id))
		else:
			await db.delete('qc_phrases', where=dict(channel_id=ctx.channel.id))

	@staticmethod
	async def noadd(ctx, member, games, moderator, reason=None):
		games = max(NoAdds.MIN_GAMES, min(NoAdds.MAX_GAMES, games))
		await db.update(
			'noadds',
			dict(is_active=0, released_by="another noadd"),
			keys=dict(channel_id=ctx.channel.id, user_id=member.id, is_active=1)
		)
		await db.insert('noadds', dict(
			guild_id=ctx.channel.guild.id,
			channel_id=ctx.channel.id,
			user_id=member.id,
			name=get_nick(member),
			at=int(time.time()),
			games_remaining=games,
			reason=reason,
			by=get_nick(moderator)
		))
		return games

	@staticmethod
	async def forgive(ctx, member, moderator):
		noadd_id = await db.select_one(
			['id'], 'noadds', where=dict(channel_id=ctx.channel.id, user_id=member.id, is_active=1)
		)
		if not noadd_id:
			return False
		await db.update(
			'noadds',
			dict(is_active=0, released_by=get_nick(moderator)),
			keys=noadd_id
		)
		return True

	@staticmethod
	async def get_noadds(ctx):
		return await db.select(['*'], 'noadds', where=dict(channel_id=ctx.channel.id, is_active=1))

	@staticmethod
	async def tick_games(channel_id):
		""" Called once per match that starts on this channel (bot/match/
			match.py, Match.new) -- decrements every active ban's remaining
			game count by one, releasing any that reach zero. """
		rows = await db.select(['id', 'games_remaining'], 'noadds', where=dict(channel_id=channel_id, is_active=1))
		for row in rows:
			remaining = (row['games_remaining'] or 0) - 1
			if remaining <= 0:
				await db.update(
					'noadds', dict(games_remaining=0, is_active=0, released_by="served"), keys=dict(id=row['id'])
				)
			else:
				await db.update('noadds', dict(games_remaining=remaining), keys=dict(id=row['id']))


noadds = NoAdds()
