# -*- coding: utf-8 -*-
import bot
from bot import soracle
from core.utils import join_and, get_nick
from core.console import log


class AutoBalance:
	""" Applies Soracle's Perfect Balance suggestion to the match automatically — no menu,
		no reactions, no vote. Queues over 12 players always fall back to manual picks (Soracle
		only balances exactly 12). On any other failure (unlinked players, Soracle down) the
		match drops into the untouched vanilla draft flow. Doesn't post its own message — the
		result rides in Match.final_message() so a queue popping shows one message, not two. """

	def __init__(self, match):
		self.m = match
		self.last_option = None  # the applied Soracle option, for final_message() to read

		if bot.soracle.enabled() and self.m.cfg['soracle_balance'] and self.m.cfg['pick_teams'] == "draft":
			self.m.states.append(self.m.BALANCE)

	async def start(self, ctx):
		""" Runs once when the match reaches the BALANCE state, with DRAFT still ahead in
			the state queue. Whether or not a balance gets applied, next_state() always
			follows — either DRAFT is still there to catch a failure, or apply() has
			already removed it because the teams are set. """
		await self._fetch_and_apply(ctx)
		await self.m.next_state(ctx)

	async def rebalance(self, ctx, author):
		""" =rebalance: from the draft stage, recompute and re-apply Perfect Balance.
			Available to a team captain, otherwise requires a moderator. """
		if self.m.state != self.m.DRAFT:
			raise bot.Exc.MatchStateError(self.m.gt("The match is not on the draft stage."))
		if not (bot.soracle.enabled() and self.m.cfg['soracle_balance'] and self.m.cfg['pick_teams'] == "draft"):
			raise bot.Exc.NotFoundError(self.m.gt("Auto-balancing is not enabled on this queue."))
		if author not in self.m.captains[:2]:
			ctx.check_perms(ctx.Perms.MODERATOR)

		log.info(f"Match {self.m.id}: {get_nick(author)} requested a rebalance.")
		# Current state IS the draft (states holds only what's still ahead, e.g. waiting-report
		# for ranked queues), so a failed apply must leave the match right here rather than
		# falling through to next_state() and skipping the draft it's already on.
		if not await self._fetch_and_apply(ctx):
			return
		await self.m.next_state(ctx)

	async def go_manual(self, ctx, author):
		""" =manual: admin-only. Send a match with Soracle-applied teams back to the draft
			stage for manual picking. """
		if self.m.state not in (self.m.DRAFT, self.m.WAITING_REPORT):
			raise bot.Exc.MatchStateError(self.m.gt("The match has already finished."))
		if self.m.state == self.m.DRAFT:
			raise bot.Exc.MatchStateError(self.m.gt("The match is already on manual picks."))
		if not (bot.soracle.enabled() and self.m.cfg['soracle_balance']):
			raise bot.Exc.NotFoundError(self.m.gt("Auto-balancing is not enabled on this queue."))
		ctx.check_perms(ctx.Perms.MODERATOR)

		# Keep whoever currently leads each team as captain instead of reverting to the
		# original auto-picked pair — mirrors the old =capfor-preserving behaviour.
		leads = [t[0] for t in self.m.teams[:2] if len(t)] or self.m.captains[:2]
		self.m.teams[2].set([p for p in self.m.players if p not in leads])
		self.m.teams[0].set(leads[:1])
		self.m.teams[1].set(leads[1:2])
		self.m.captains = leads
		self.last_option = None  # picks are manual again — final_message() shouldn't show stale tiers

		self.m.states = [self.m.WAITING_REPORT] if self.m.ranked else []
		self.m.state = self.m.DRAFT
		log.info(f"Match {self.m.id}: {get_nick(author)} reverted the match to manual picks.")
		await ctx.notice("\n".join((
			self.m.gt("Reverted to manual picks."),
			self.m.gt("A captain can type {cmd} to auto-balance the teams again.").format(
				cmd=f"`{self.m.qc.cfg.prefix}rebalance`"
			)
		)))
		await self.m.draft.start(ctx)

	async def _fetch_and_apply(self, ctx):
		""" Fetches Soracle's Perfect Balance suggestion and applies it. Returns True on
			success (teams set, last_option recorded for final_message(), DRAFT dropped
			from the state queue if it was still ahead). On any failure, notifies and
			returns False. """
		if len(self.m.players) > 12:
			await ctx.notice("\n".join((
				self.m.gt("Auto-balancing supports 12 players — proceeding to manual picks."),
				self.m.gt("Go to {url} to build a balance for your own selection of 12 players.").format(
					url=soracle.balancer_url()
				)
			)))
			return False
		if len(self.m.players) < 12:
			# smaller formats (4v4 / 5v5) just use manual picks, no auto-balance
			log.debug(f"Match {self.m.id}: {len(self.m.players)} players, skipping Soracle auto-balance.")
			return False

		try:
			options = await soracle.fetch_balance([p.id for p in self.m.players])
		except soracle.UnlinkedError as e:
			await ctx.notice("\n".join((
				self.m.gt("{players} not linked to a site profile — skipping auto-balance.").format(
					players=join_and([f"<@{i}>" for i in e.unlinked_ids])
				),
				self.m.gt("An admin can link them on the site. Proceeding to manual picks.")
			)))
			return False
		except soracle.SoracleError as e:
			log.error(f"Soracle balance request failed for match {self.m.id}: {str(e)}")
			await ctx.notice(self.m.gt("Could not fetch a balance suggestion, proceeding to manual picks."))
			return False

		option = options[0]
		if not self._apply(option):
			log.error(f"Soracle's Perfect Balance option for match {self.m.id} did not map onto the match players.")
			await ctx.notice(self.m.gt("Could not apply the balance suggestion, proceeding to manual picks."))
			return False

		log.info(f"Match {self.m.id}: Perfect Balance applied automatically.")
		return True

	def _apply(self, option):
		""" Maps a Soracle option onto match players and sets teams. Returns False (teams
			untouched) if the option's ids don't match this match's roster. """
		members = {p.id: p for p in self.m.players}
		teams = []
		for key in ('teamRedDiscordIds', 'teamBlueDiscordIds'):
			team = [members[int(i)] for i in (option.get(key) or []) if i and int(i) in members]
			teams.append(team)

		if sorted((p.id for t in teams for p in t)) != sorted(members.keys()):
			return False

		# Keep the current team leads as captains (team[0] reports the result): sort by
		# rating, then move a lead to the front of their team.
		leads = [t[0] for t in self.m.teams[:2] if len(t)] or self.m.captains[:2]
		for n in (0, 1):
			team = self.m.sort_players(teams[n])
			if lead := next((c for c in leads if c in team), None):
				team.remove(lead)
				team.insert(0, lead)
			self.m.teams[n].set(team)
		self.m.teams[2].clear()
		self.m.captains = [t[0] for t in self.m.teams[:2] if len(t)]
		self.last_option = option

		if self.m.DRAFT in self.m.states:
			self.m.states.remove(self.m.DRAFT)
		return True
