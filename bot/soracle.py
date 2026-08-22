# -*- coding: utf-8 -*-
""" Thin client for the Soracle bot API. The bot contains no balancing logic —
	teams and player data always come from Soracle over this client. """

import asyncio
import aiohttp

from core.config import cfg

def enabled():
	""" Master switch for the whole Soracle integration. When False the bot runs as
		plain PUBobot2 + manual picking: stats/balance commands are hidden, no balance
		suggestions are posted, and scoreboards aren't uploaded. Defaults to True so a
		config without the flag behaves as before. """
	return getattr(cfg, 'SORACLE_ENABLED', True)


def site_url():
	""" The public site, for anything a player will read or click: profile links,
		embed titles, "log this game" nudges.

		Deliberately not SORACLE_API_URL. That stays pinned to the Vercel host the
		bot talks to over HTTP — nobody ever sees it, and it cannot lapse. This is
		the community domain, and it is the only one that belongs in Discord. The
		two used to be the same site, so reaching for whichever was already in
		scope looked harmless; it isn't any more. """
	return getattr(cfg, 'PUBLIC_SITE_URL', 'https://jk2ctf.com').rstrip('/')


def balancer_url():
	""" The site's manual balance-options page — for anyone who wants something other
		than the auto-applied Perfect Balance split (a different 12 players, a different
		suggestion). Replaces the old in-Discord option picker. """
	return f"{site_url()}/balancer"


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
		raise SoracleError("Could not reach the stats site.")


async def upload_scoreboard(payload_bytes, filename, *, guild_id=None, channel_id=None,
                            message_id=None, user_id=None, username=None):
	""" Upload an end-of-match scoreboard to Soracle's approval queue. Accepts
		either format — Soracle picks the parser off the filename extension.

		Returns (status, data): on success status 200 with data like
		{pending_id, distinct, matched, unmatched}, or {skipped: True, reason}
		for sub-12-player games, or {duplicate: True} on a repeat of the same
		Discord message. Raises SoracleError if the stats site is unreachable. """
	url = cfg.SORACLE_API_URL + "/api/bot/scoreboard"
	headers = {'Authorization': f"Bearer {cfg.SORACLE_API_SECRET}"}

	form = aiohttp.FormData()
	content_type = 'application/json' if filename.lower().endswith('.json') else 'text/csv'
	form.add_field('file', payload_bytes, filename=filename, content_type=content_type)
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
		raise SoracleError("Could not reach the stats site.")


async def fetch_player(discord_id):
	""" Returns dict(name, tier, roles, tooltip) or None if the discord id is unlinked. """
	status, data = await _request('GET', f"/api/bot/player/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_player_stats(discord_id):
	""" Month-to-date stats dict for a player, or None if the discord id is unlinked. """
	status, data = await _request('GET', f"/api/bot/stats/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_achievements(discord_id):
	""" A player's top earned achievements, or None if the discord id is unlinked. """
	status, data = await _request('GET', f"/api/bot/achievements/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_nemesis(discord_id):
	""" A player's worst head-to-head this month, or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/nemesis/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_friend(discord_id):
	""" A player's best team-mate this month, or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/friend/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_curse(discord_id):
	""" A player's worst team-mate this month (most-lost-alongside), or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/curse/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_redblue(discord_id):
	""" A player's all-time W/L on the Red base vs the Blue base, or None if unlinked. """
	status, data = await _request('GET', f"/api/bot/redblue/by-discord/{discord_id}")
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_last_match(discord_id=None):
	""" The most recent match recorded on Soracle (with scoreboard). With a discord_id,
		returns that player's last match instead. None if there's no match (or, for a
		player, if they're unlinked / have no recorded games). """
	path = "/api/bot/last-match" + (f"?discordId={discord_id}" if discord_id else "")
	status, data = await _request('GET', path)
	if status == 404:
		return None
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


def _month_qs(year, month):
	return f"?year={year}&month={month}" if year and month else ""


async def fetch_monthly_report(year=None, month=None):
	""" Star player + rivalries for a month (default current): dict(month, starPlayer, rivalries, ...). """
	status, data = await _request('GET', "/api/bot/monthly-report" + _month_qs(year, month))
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_monthly_aggregates(year=None, month=None):
	""" Per-player summed stats for a month (default current): dict(month, matchCount, players=[...]). """
	status, data = await _request('GET', "/api/bot/monthly-aggregates" + _month_qs(year, month))
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_stat_leaderboard(stat, all_time=False):
	""" Top players by a match-stat: dict(stat, label, month, top=[{name, value}]).
		Defaults to the current month; all_time=True sums the whole history, for
		stats too rare to fill a monthly board (see =doom). `month` comes back as
		"all time" in that case, so the embed title reads correctly either way. """
	suffix = "?range=all" if all_time else ""
	status, data = await _request('GET', f"/api/bot/leaderboard/{stat}{suffix}")
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_cap_conversion():
	""" Cap conversion board: dict(window, matchCount, carryFloor, top=[...]).

		Not a monthly board. It reads the per-opponent kill matrix, which only
		exists from 9 Aug 2026 and can't be backfilled, so the window is "since
		tracking began" and `matchCount` says how many games back it. Anything
		presenting this to players must not imply a longer history. """
	status, data = await _request('GET', "/api/bot/cap-conversion")
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_returner_rate():
	""" Top returners: dict(month, gameFloor, top=[...]).

		Rate is measured over each player's returner games only — Soracle works out
		who played returner in each match from flag hold and mine grabs, because
		counting cap and mine-clearing games ranked players by the role they were
		given rather than how well they returned. """
	status, data = await _request('GET', "/api/bot/returner-rate")
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
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
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data['options']
