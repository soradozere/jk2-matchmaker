# -*- coding: utf-8 -*-
""" Thin client for the Soracle bot API. The bot contains no balancing logic —
	teams and player data always come from Soracle over this client. """

import asyncio
import aiohttp

from core.config import cfg

TIMEOUT = aiohttp.ClientTimeout(total=5)
# Scoreboard uploads do more work server-side (parse, resolve names, store CSV),
# so they get a longer budget than the read-only calls.
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SoracleError(Exception):
	""" Soracle was unreachable or returned an unexpected response. """


class UnlinkedError(SoracleError):
	""" One or more discord ids are not linked to a Soracle player. """

	def __init__(self, unlinked_ids):
		super().__init__("unlinked")
		self.unlinked_ids = unlinked_ids


async def _request(method, path, json_body=None):
	url = cfg.SORACLE_API_URL + path
	headers = {'Authorization': f"Bearer {cfg.SORACLE_API_SECRET}"}
	try:
		async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
			async with session.request(method, url, headers=headers, json=json_body) as resp:
				try:
					data = await resp.json(content_type=None)
				except ValueError:
					data = None
				return resp.status, data
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise SoracleError("Could not reach Soracle.")


async def upload_scoreboard(csv_bytes, filename, *, guild_id=None, channel_id=None,
                            message_id=None, user_id=None, username=None):
	""" Upload an end-of-match scoreboard CSV to Soracle's approval queue.

		Returns (status, data): on success status 200 with data like
		{pending_id, distinct, matched, unmatched}, or {skipped: True, reason}
		for sub-12-player games, or {duplicate: True} on a repeat of the same
		Discord message. Raises SoracleError if Soracle is unreachable. """
	url = cfg.SORACLE_API_URL + "/api/bot/scoreboard"
	headers = {'Authorization': f"Bearer {cfg.SORACLE_API_SECRET}"}

	form = aiohttp.FormData()
	form.add_field('file', csv_bytes, filename=filename, content_type='text/csv')
	for key, value in (
		('filename', filename),
		('guild_id', guild_id),
		('channel_id', channel_id),
		('message_id', message_id),
		('user_id', user_id),
		('username', username),
	):
		if value is not None:
			form.add_field(key, str(value))

	try:
		async with aiohttp.ClientSession(timeout=UPLOAD_TIMEOUT) as session:
			async with session.post(url, headers=headers, data=form) as resp:
				try:
					data = await resp.json(content_type=None)
				except ValueError:
					data = None
				return resp.status, data
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise SoracleError("Could not reach Soracle.")


async def fetch_player(discord_id):
	""" Returns dict(name, tier, roles, tooltip) or None if the discord id is unlinked. """
	status, data = await _request('GET', f"/api/bot/player/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_player_stats(discord_id):
	""" Month-to-date stats dict for a player, or None if the discord id is unlinked. """
	status, data = await _request('GET', f"/api/bot/stats/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_nemesis(discord_id):
	""" A player's worst head-to-head this month, or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/nemesis/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_friend(discord_id):
	""" A player's best team-mate this month, or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/friend/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_last_match():
	""" The most recent match recorded on Soracle (with scoreboard), or None if none. """
	status, data = await _request('GET', "/api/bot/last-match")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


def _month_qs(year, month):
	return f"?year={year}&month={month}" if year and month else ""


async def fetch_monthly_report(year=None, month=None):
	""" Star player + rivalries for a month (default current): dict(month, starPlayer, rivalries, ...). """
	status, data = await _request('GET', "/api/bot/monthly-report" + _month_qs(year, month))
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_monthly_aggregates(year=None, month=None):
	""" Per-player summed stats for a month (default current): dict(month, matchCount, players=[...]). """
	status, data = await _request('GET', "/api/bot/monthly-aggregates" + _month_qs(year, month))
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_stat_leaderboard(stat):
	""" Top players by a match-stat for the current month: dict(stat, label, month, top=[{name, value}]). """
	status, data = await _request('GET', f"/api/bot/leaderboard/{stat}")
	if status != 200 or data is None:
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data


async def fetch_balance(discord_ids):
	""" Returns the list of balance options for exactly 12 discord ids.
		Each option carries result.teamRed/teamBlue (names), tier totals, mic counts
		and teamRedDiscordIds/teamBlueDiscordIds for mapping back to members.
		Raises UnlinkedError if any id is not linked to a Soracle player. """
	status, data = await _request(
		'POST', "/api/bot/balance", json_body=dict(discordIds=[str(i) for i in discord_ids])
	)
	if status == 422 and data and data.get('error') == "unlinked":
		raise UnlinkedError(data.get('unlinkedIds') or [])
	if status != 200 or not data or not data.get('options'):
		raise SoracleError(f"Soracle returned an unexpected response (HTTP {status}).")
	return data['options']
