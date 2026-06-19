# -*- coding: utf-8 -*-
from time import time
from nextcord import DiscordException

import bot
from bot import soracle
from core.config import cfg
from core.utils import join_and, get_nick
from core.console import log


class BalanceMenu:
	""" Fetches balanced team suggestions from Soracle when the queue starts and lets
		the captains accept one, cycle through the options or fall back to manual picks.
		On any failure (unlinked players, Soracle down, wrong queue size) the match
		drops into the untouched vanilla draft flow. """

	ACCEPT_EMOJI = "✅"
	OPTION_EMOJIS = ["1️⃣", "2️⃣", "3️⃣"]
	MANUAL_EMOJI = "✋"

	def __init__(self, match):
		self.m = match
		self.timeout = match.cfg['soracle_balance_timeout']  # 0 disables auto-accept
		self.message = None
		self.options = []
		self.idx = 0
		self.accepts = set()
		self.started_at = None

		if self.m.cfg['soracle_balance'] and self.m.cfg['pick_teams'] == "draft":
			self.m.states.append(self.m.BALANCE)

	@property
	def approvers(self):
		""" Members whose ✅ counts. The two vanilla-picked captains if present,
			otherwise (pick_captains is 'no captains') any two match players. """
		return self.m.captains[:2]

	@property
	def option(self):
		return self.options[self.idx]

	async def start(self, ctx):
		if len(self.m.players) > 12:
			await ctx.notice("\n".join((
				self.m.gt("Soracle balancing supports 12 players — proceeding to manual picks."),
				self.m.gt("Go to {url} to create a balance based on your own selection of 12 players.").format(
					url=cfg.SORACLE_API_URL
				)
			)))
			await self.m.next_state(ctx)
			return
		if len(self.m.players) < 12:
			# smaller formats (4v4 / 5v5) just use manual picks, no menu and no link
			log.debug(f"Match {self.m.id}: {len(self.m.players)} players, skipping Soracle balance menu.")
			await self.m.next_state(ctx)
			return

		try:
			self.options = await soracle.fetch_balance([p.id for p in self.m.players])
		except soracle.UnlinkedError as e:
			await ctx.notice("\n".join((
				self.m.gt("{players} not linked to Soracle — skipping balance suggestions.").format(
					players=join_and([f"<@{i}>" for i in e.unlinked_ids])
				),
				self.m.gt("An admin can link them on Soracle. Proceeding to manual picks.")
			)))
			await self.m.next_state(ctx)
			return
		except soracle.SoracleError as e:
			log.error(f"Soracle balance request failed for match {self.m.id}: {str(e)}")
			await ctx.notice(self.m.gt("Could not get balance suggestions from Soracle, proceeding to manual picks."))
			await self.m.next_state(ctx)
			return

		self.idx = 0
		self.accepts = set()
		try:
			pings = " ".join(p.mention for p in self.m.players)
			self.message = await ctx.channel.send(content=pings, embed=self.m.embeds.balance_menu(self))
		except DiscordException as e:
			log.error(f"Match {self.m.id}: failed to post the balance menu: {str(e)}")
			await self.m.next_state(ctx)
			return
		try:
			for emoji in (*self.OPTION_EMOJIS[:len(self.options)], self.ACCEPT_EMOJI, self.MANUAL_EMOJI):
				await self.message.add_reaction(emoji)
		except DiscordException as e:
			# usually missing Add Reactions or Read Message History on the channel
			log.error(f"Match {self.m.id}: failed to add menu reactions: {str(e)}")
			try:
				await self.message.delete()
			except DiscordException:
				pass
			self.message = None
			try:
				await ctx.notice(self.m.gt(
					"I lack channel permissions to run the balance menu (Add Reactions / Read Message History), "
					"proceeding to manual picks."
				))
			except DiscordException:
				pass
			await self.m.next_state(ctx)
			return

		self.started_at = int(time())
		bot.waiting_reactions[self.message.id] = self.process_reaction
		log.info(f"Match {self.m.id}: balance menu posted, captains: {[get_nick(c) for c in self.approvers]}")

	async def think(self, frame_time):
		if self.message and self.started_at and self.timeout and frame_time > self.started_at + self.timeout:
			ctx = bot.SystemContext(self.m.qc)
			log.info(f"Match {self.m.id}: balance menu timed out, auto-accepting option {self.idx + 1}")
			await ctx.notice(self.m.gt("No captain decision in time, accepting suggestion **{n}**.").format(n=self.idx + 1))
			await self.accept(ctx)

	async def refresh(self):
		try:
			await self.message.edit(embed=self.m.embeds.balance_menu(self))
		except DiscordException:
			pass

	async def process_reaction(self, reaction, user, remove=False):
		# Reactions act as momentary buttons: we drop the user's reaction after reading it
		# so a re-click always re-fires (Discord otherwise toggles an existing reaction off).
		# Removals therefore carry no meaning.
		if remove or self.m.state != self.m.BALANCE:
			return

		try:
			await self.message.remove_reaction(reaction.emoji, user)
		except DiscordException:
			pass

		approvers = self.approvers
		if approvers and user not in approvers:
			return
		if not approvers and user not in self.m.players:
			return

		emoji = str(reaction)
		ctx = bot.SystemContext(self.m.qc)

		if emoji == self.ACCEPT_EMOJI:
			self.accepts.add(user)
			log.info(f"Match {self.m.id}: {get_nick(user)} accepted option {self.idx + 1} ({len(self.accepts)} accepts)")
			# every approver must have accepted; with no captains configured, any two players
			if (all(c in self.accepts for c in approvers) if approvers else len(self.accepts) >= 2):
				await self.accept(ctx)
			else:
				await self.refresh()

		elif emoji in self.OPTION_EMOJIS:
			new_idx = self.OPTION_EMOJIS.index(emoji)
			if new_idx < len(self.options) and new_idx != self.idx:
				self.idx = new_idx
				self.accepts = set()
				log.info(f"Match {self.m.id}: {get_nick(user)} switched to option {self.idx + 1}")
				await self.refresh()

		elif emoji == self.MANUAL_EMOJI:
			log.info(f"Match {self.m.id}: {get_nick(user)} chose manual picks")
			await self.go_manual(ctx)

	async def accept(self, ctx):
		if not await self.close_menu():
			return  # another accept/manual already won the race

		members = {p.id: p for p in self.m.players}
		option = self.option
		teams = []
		for key in ('teamRedDiscordIds', 'teamBlueDiscordIds'):
			team = [members[int(i)] for i in (option.get(key) or []) if i and int(i) in members]
			teams.append(team)

		if sorted((p.id for t in teams for p in t)) != sorted(members.keys()):
			log.error(f"Soracle option {self.idx} for match {self.m.id} did not map onto the match players.")
			await ctx.notice(self.m.gt("Could not apply the Soracle suggestion, proceeding to manual picks."))
			await self.m.next_state(ctx)
			return

		# Keep the menu captains as team captains (team[0] reports the result):
		# sort by rating, then move a menu captain to the front of their team.
		for n in (0, 1):
			team = self.m.sort_players(teams[n])
			if captain := next((c for c in self.m.captains[:2] if c in team), None):
				team.remove(captain)
				team.insert(0, captain)
			self.m.teams[n].set(team)
		self.m.teams[2].clear()
		self.m.captains = [t[0] for t in self.m.teams[:2] if len(t)]

		# Teams are final — skip the draft stage entirely
		if self.m.DRAFT in self.m.states:
			self.m.states.remove(self.m.DRAFT)

		msg = self.m.gt("Suggestion **{n}** ({label}) accepted!").format(
			n=self.idx + 1, label=option.get('label') or "—"
		)
		if self.m.ranked:
			msg += "\n" + self.m.gt("A captain can type {cmd} before reporting to redo the teams.").format(
				cmd=f"`{self.m.qc.cfg.prefix}rebalance`"
			)
		await ctx.notice(msg)
		await self.m.next_state(ctx)

	async def go_manual(self, ctx):
		if not await self.close_menu():
			return
		await ctx.notice("\n".join((
			self.m.gt("Proceeding to manual team picking."),
			self.m.gt("A captain can type {cmd} to return to the Soracle suggestions.").format(
				cmd=f"`{self.m.qc.cfg.prefix}rebalance`"
			)
		)))
		await self.m.next_state(ctx)

	async def reopen(self, ctx, author):
		""" Return a match to the balance menu (=rebalance) — from manual picking,
			or from the waiting-report stage after a timeout auto-accepted teams. """
		if self.m.state not in (self.m.DRAFT, self.m.WAITING_REPORT):
			raise bot.Exc.MatchStateError(self.m.gt("The match has already finished."))
		if not (self.m.cfg['soracle_balance'] and self.m.cfg['pick_teams'] == "draft"):
			raise bot.Exc.NotFoundError(self.m.gt("Soracle balancing is not enabled on this queue."))
		# The menu buttons belong to whoever leads the teams NOW — a =capfor'd captain
		# keeps control through a rebalance instead of reverting to the auto-picked pair.
		current_leads = [t[0] for t in self.m.teams[:2] if len(t)]
		for previous in self.m.captains:
			if len(current_leads) >= 2:
				break
			if previous not in current_leads and previous in self.m.players:
				current_leads.append(previous)
		if current_leads:
			self.m.captains = current_leads[:2]

		if author not in self.m.captains[:2]:
			ctx.check_perms(ctx.Perms.MODERATOR)

		log.info(f"Match {self.m.id}: {get_nick(author)} reopened the balance menu (from {self.m.state})")
		# Rebuild the state queue: draft as the manual fallback, then waiting-report if ranked.
		if self.m.state == self.m.WAITING_REPORT:
			self.m.states = [self.m.DRAFT] + ([self.m.WAITING_REPORT] if self.m.ranked else [])
		else:
			self.m.states.insert(0, self.m.DRAFT)
		self.m.state = self.m.BALANCE
		await ctx.notice(self.m.gt("Returning to the Soracle balance suggestions..."))
		await self.start(ctx)

	async def close_menu(self):
		""" Returns True for the single caller that actually closed the menu.
			No await before self.message is cleared, so this is race-free on the event loop. """
		if (message := self.message) is None:
			return False
		self.message = None
		bot.waiting_reactions.pop(message.id, None)
		try:
			await message.delete()
		except DiscordException:
			pass
		return True
