# -*- coding: utf-8 -*-
""" Thin client for Urban Dictionary's public (unofficial but stable, no key
	required) lookup API. Powers the =urban / /urban command. """

import asyncio
import aiohttp

API_URL = "https://api.urbandictionary.com/v0/define"
TIMEOUT = aiohttp.ClientTimeout(total=5)


class UrbanError(Exception):
	""" Urban Dictionary was unreachable or returned an unexpected response. """


async def define(term):
	""" Returns Urban Dictionary's definitions for `term`, best-rated first (the
		API's own ordering) — empty list if nothing matched. """
	try:
		async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
			async with session.get(API_URL, params={'term': term}) as resp:
				if resp.status != 200:
					raise UrbanError(f"Urban Dictionary returned HTTP {resp.status}.")
				try:
					data = await resp.json(content_type=None)
				except ValueError:
					raise UrbanError("Urban Dictionary returned an unexpected response.")
	except (aiohttp.ClientError, asyncio.TimeoutError):
		raise UrbanError("Could not reach Urban Dictionary.")
	return (data or {}).get('list') or []
