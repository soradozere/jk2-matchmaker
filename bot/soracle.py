# -*- coding: utf-8 -*-
""" Thin client for the Soracle bot API. The bot contains no balancing logic —
	teams and player data always come from Soracle over this client. """

import asyncio
import aiohttp

from core.config import cfg

TIMEOUT = aiohttp.ClientTimeout(total=5)


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
