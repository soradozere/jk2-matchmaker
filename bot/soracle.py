# -*- coding: utf-8 -*-
""" Thin client for the Soracle bot API. The bot contains no balancing logic —
	teams and player data always come from Soracle over this client. """

import asyncio
import aiohttp
from urllib.parse import quote

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


async def fetch_tier_changelog(since=None):
	""" Tier changes since a given ISO timestamp, oldest first, capped at 500 rows:
		dict(changes=[{discordId, name, oldTier, newTier, at, source}]).
		Omit `since` for full history (only safe to do once, to baseline a cursor --
		don't announce results from an unbounded call, it'll include real past
		history). discordId can be None for an unlinked player -- still a real
		change, worth announcing by name without a mention. source is "calibrator"
		or "admin". """
	qs = f"?since={quote(since)}" if since else ""
	status, data = await _request('GET', "/api/bot/tier-changelog" + qs)
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_title_changelog(since=None):
	""" Equipped-title changes since a given ISO timestamp, oldest first, capped at
		500 rows: dict(changes=[{discordId, name, oldTitle, newTitle, rarity, at}]).
		Same unbounded-`since` caveat as fetch_tier_changelog. oldTitle=None means
		this is their first title ever; newTitle=None (and rarity=None) means they
		unequipped -- both are meaningful nulls, not missing data. discordId can be
		None the same way as the tier changelog. """
	qs = f"?since={quote(since)}" if since else ""
	status, data = await _request('GET', "/api/bot/title-changelog" + qs)
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


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


async def fetch_stat_leaderboard(stat, all_time=False, period=None):
	""" Top players by a match-stat: dict(stat, label, month, top=[{name, value}]).
		Defaults to the current month; all_time=True sums the whole history, for
		stats too rare to fill a monthly board (see =doom). `month` comes back as
		"all time" in that case, so the embed title reads correctly either way.
		period ("day"/"week"/"month"/"year") is an alternative window, used by
		/top -- mutually exclusive with all_time in practice, but this just
		forwards whichever query params are given. """
	params = []
	if all_time:
		params.append("range=all")
	if period:
		params.append(f"period={period}")
	suffix = ("?" + "&".join(params)) if params else ""
	status, data = await _request('GET', f"/api/bot/leaderboard/{stat}{suffix}")
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	return data


async def fetch_cap_conversion(year=None, month=None):
	""" Cap conversion board for a month (default current):
		dict(month, matchCount, carryFloor, top=[...]).

		Scoped to a calendar month like the other monthly boards. It reads the
		per-opponent kill matrix, which only exists from 9 Aug 2026 and can't be
		backfilled — every full month from Sep 2026 on is clean, but don't offer
		a month picker that reaches back past that. """
	status, data = await _request('GET', "/api/bot/cap-conversion" + _month_qs(year, month))
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


async def fetch_player_summaries(discord_ids):
	""" Batched name+tier lookup for a group of players: dict(int(discord_id) ->
		dict(name, tier)). A discord_id that isn't linked to a Soracle player is
		simply absent from the result, not an error -- callers should treat a
		missing id as unknown. Used wherever a whole queue's worth of players'
		identity/skill is needed at once (captain selection): fetching each
		player individually (fetch_player, one call each) would mean N round
		trips right when a queue fills. """
	status, data = await _request(
		'POST', "/api/bot/tiers", json_body=dict(discordIds=[str(i) for i in discord_ids])
	)
	if status != 200 or data is None:
		raise SoracleError(f"The stats site returned an unexpected response (HTTP {status}).")
	tiers, names = data.get('tiers') or {}, data.get('names') or {}
	return {
		int(k): dict(name=names.get(k), tier=tiers.get(k))
		for k in tiers.keys() | names.keys()
	}


async def fetch_tiers(discord_ids):
	""" Batched tier-only lookup -- see fetch_player_summaries. Kept separate
		since most callers (tier-based fair-pairs captains) only need the tier. """
	summaries = await fetch_player_summaries(discord_ids)
	return {i: s['tier'] for i, s in summaries.items() if s.get('tier') is not None}


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
