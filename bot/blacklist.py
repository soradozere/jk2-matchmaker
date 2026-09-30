# -*- coding: utf-8 -*-
""" Dated blacklist: a player listed here cannot be added to any queue, on
	any channel, by themselves or by a moderator, until the date passes.

	Separate from noadds (bot/stats/noadds.py) because that is counted in
	matches, capped at 5, and per channel -- none of which fits "not until
	a date". Edit the list and redeploy; entries past their date do nothing
	and can be removed whenever. """

from datetime import datetime, timezone

from core.config import cfg
import bot

# (user_id, lifts_at, message)
# Times are UTC. 20 Oct 2026 00:00 UK time is 19 Oct 23:00 UTC (BST until
# the 25th), so "until the 20th" means the 20th itself is playable.
ENTRIES = [
	(
		cfg.DC_OWNER_ID,
		datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc),
		"Blacklisted until 20th October 2026",
	),
]


def check(member):
	""" Raises PermissionError if member is blacklisted right now. """
	now = datetime.now(timezone.utc)
	for user_id, lifts_at, message in ENTRIES:
		if member.id == user_id and now < lifts_at:
			raise bot.Exc.BlacklistedError(message)
