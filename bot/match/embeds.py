from nextcord import Embed, Colour, Streaming, Member
from core.client import dc
from core.utils import get_nick, join_and
from bot import soracle


class Embeds:
	""" This class generates discord embeds for various match states """

	def __init__(self, match):
		self.m = match
		# self.
		self.footer = dict(
			text=f"Match id: {self.m.id}",
			icon_url=dc.user.avatar.with_size(32).url if dc.user.avatar else None
			# icon_url="https://cdn.discordapp.com/avatars/240843400457355264/a51a5bf3b34d94922fd60751ba1d60ab.png?size=64"
		)

	def _ranked_nick(self, p: Member):
		if self.m.ranked:
			if self.m.qc.cfg.emoji_ranks:
				return f'{self.m.rank_str(p)}`{get_nick(p)}`'
			return f'`{self.m.rank_str(p)}{get_nick(p)}`'
		return f'`{get_nick(p)}`'

	def _ranked_mention(self, p: Member):
		if self.m.ranked:
			if self.m.qc.cfg.emoji_ranks:
				return f'{self.m.rank_str(p)}{p.mention}'
			return f'`{self.m.rank_str(p)}`{p.mention}'
		return p.mention

	def _ranked_display(self, p: Member, name: str):
		""" Like _ranked_nick, but with a caller-supplied display name — used to show the
			name Soracle has on record (the balancer site's name) instead of the Discord
			nickname, when a balance option is available to read it from. """
		if self.m.ranked:
			if self.m.qc.cfg.emoji_ranks:
				return f'{self.m.rank_str(p)}`{name}`'
			return f'`{self.m.rank_str(p)}{name}`'
		return f'`{name}`'

	def _team_avg_rating(self, team):
		return sum((self.m.ratings[p.id] for p in team)) // (len(team) or 1)

	def check_in(self, not_ready):
		embed = Embed(
			colour=Colour(0xf5d858),
			title=self.m.gt("__**{queue}** is now on the check-in stage!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)
		embed.add_field(
			name=self.m.gt("Waiting on:"),
			value="\n".join((f" \u200b {'❌ ' if p in self.m.check_in.discarded_players else ''}<@{p.id}>" for p in not_ready)),
			inline=False
		)
		if not len(self.m.check_in.maps):
			embed.add_field(
				name="—",
				value=self.m.gt(
					"Please react with {ready_emoji} to **check-in** or {not_ready_emoji} to **abort**!").format(
					ready_emoji=self.m.check_in.READY_EMOJI, not_ready_emoji=self.m.check_in.NOT_READY_EMOJI
				) + "\n\u200b",
				inline=False
			)
		else:
			embed.add_field(
				name="—",
				value="\n".join([
					self.m.gt("Please react with {ready_emoji} or vote for a map to **check-in**.").format(
						ready_emoji=self.m.check_in.READY_EMOJI
					),
					self.m.gt("React with {not_ready_emoji} to **abort**!").format(
						not_ready_emoji=self.m.check_in.NOT_READY_EMOJI
					) + "\n\u200b\nMaps:",
					"\n".join([
						f" \u200b \u200b {self.m.check_in.INT_EMOJIS[i]} \u200b {self.m.check_in.maps[i]}"
						for i in range(len(self.m.check_in.maps))
					])
				]),
				inline=False
			)
		embed.set_footer(**self.footer)

		return embed

	def draft(self):
		embed = Embed(
			colour=Colour(0x8758f5),
			title=self.m.gt("__**{queue}** is now on the draft stage!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)

		teams_names = [
			f"{t.emoji} \u200b **{t.name}**" +
			(f" \u200b `〈{self._team_avg_rating(t)}〉`" if self.m.ranked else "")
			for t in self.m.teams[:2]
		]
		team_players = [
			" \u200b ".join([
				self._ranked_nick(p) for p in t
			]) if len(t) else self.m.gt("empty")
			for t in self.m.teams[:2]
		]
		embed.add_field(name=teams_names[0], value=" \u200b ❲ \u200b " + team_players[0] + " \u200b ❳", inline=False)
		embed.add_field(name=teams_names[1], value=" \u200b ❲ \u200b " + team_players[1] + " \u200b ❳\n\u200b", inline=False)

		if len(self.m.teams[2]):
			embed.add_field(
				name=self.m.gt("Unpicked:"),
				value="\n".join((
					" \u200b " + self._ranked_nick(p)
				) for p in self.m.teams[2]),
				inline=False
			)

			if len(self.m.teams[0]) and len(self.m.teams[1]):
				msg = self.m.gt("Pick players with `/pick @player` command.")
				pick_step = len(self.m.teams[0]) + len(self.m.teams[1]) - 2
				picker_team = self.m.teams[self.m.draft.pick_order[pick_step]] if pick_step < len(self.m.draft.pick_order)-1 else None
				if picker_team:
					msg += "\n" + self.m.gt("{member}'s turn to pick!").format(member=f"<@{picker_team[0].id}>")
			else:
				msg = self.m.gt("Type {cmd} to become a captain and start picking teams.").format(
					cmd=f"`{self.m.qc.cfg.prefix}capfor {'/'.join((team.name.lower() for team in self.m.teams[:2]))}`"
				)

			if not self.m.cfg['soracle_balance'] and len(self.m.players) == 12:
				msg += "\n" + self.m.gt("💡 Use `{p}options` to see the balance suggestions.").format(
					p=self.m.qc.cfg.prefix
				)

			embed.add_field(name="—", value=msg + "\n\u200b", inline=False)

		embed.set_footer(**self.footer)

		return embed

	def balance_options(self, options):
		""" All Soracle suggestions in one read-only embed (=options / auto-post). """
		embed = Embed(
			colour=Colour(0x50e3c2),
			title=self.m.gt("__**{queue}** — balance suggestions__").format(
				queue=self.m.queue.name[0].upper() + self.m.queue.name[1:]
			)
		)
		members = {p.id: p for p in self.m.players}
		labels = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
		for i, opt in enumerate(options):
			result = opt.get('result') or {}
			rows = []
			for team, ids_key, names_key in (
				(self.m.teams[0], 'teamRedDiscordIds', 'teamRed'),
				(self.m.teams[1], 'teamBlueDiscordIds', 'teamBlue'),
			):
				ids = opt.get(ids_key) or []
				names = result.get(names_key) or []
				roster = " ".join(
					f"`{get_nick(members[int(x)])}`" if x and int(x) in members else f"`{names[n] if n < len(names) else '?'}`"
					for n, x in enumerate(ids)
				) or self.m.gt("empty")
				rows.append(f"{team.emoji} {roster}")
			label = opt.get('label') or self.m.gt("Option {n}").format(n=i + 1)
			embed.add_field(
				name=f"{labels[i] if i < len(labels) else str(i + 1) + '.'} {label}",
				value="\n".join(rows)[:1024],
				inline=False
			)
		embed.set_footer(text=self.m.gt("Suggestions only: set the teams manually however you like."))
		return embed

	def final_message(self):
		show_ranks = bool(self.m.ranked and not self.m.qc.cfg.rating_nicks)
		embed = Embed(
			colour=Colour(0x27b75e),
			title=self.m.qc.gt("__**{queue}** has started!__").format(
				queue=self.m.queue.name[0].upper()+self.m.queue.name[1:]
			)
		)

		if len(self.m.teams[0]) == 1 and len(self.m.teams[1]) == 1:  # 1v1
			p1, p2 = self.m.teams[0][0], self.m.teams[1][0]
			players = " \u200b {player1}{rating1}\n \u200b {player2}{rating2}".format(
				rating1=f" \u200b `〈{self.m.ratings[p1.id]}〉`" if show_ranks else "",
				player1=f"<@{p1.id}>",
				rating2=f" \u200b `〈{self.m.ratings[p2.id]}〉`" if show_ranks else "",
				player2=f"<@{p2.id}>",
			)
			embed.add_field(name=self.m.gt("Players"), value=players, inline=False)
		elif len(self.m.teams[0]):  # team vs team
			option = self.m.auto_balance.last_option
			if option:
				# Auto-balanced: bold caps team header (rating/tier/mic together) and a numbered
				# roster, inline so the two teams sit side by side — matches the site's own name
				# for each player where Soracle has it, instead of whatever their Discord nick is.
				result = option.get('result') or {}
				tier_mic_keys = (('redTierTotal', 'redMic'), ('blueTierTotal', 'blueMic'))
				soracle_names = {}
				for ids_key, names_key in (('teamRedDiscordIds', 'teamRed'), ('teamBlueDiscordIds', 'teamBlue')):
					ids, names = option.get(ids_key) or [], result.get(names_key) or []
					soracle_names.update({int(i): names[n] for n, i in enumerate(ids) if i and n < len(names)})
				for t, (tier_key, mic_key) in zip(self.m.teams[:2], tier_mic_keys):
					name = f"{t.emoji} {t.name.upper()}"
					if self.m.ranked:
						name += f" ​ `〈{self._team_avg_rating(t)}〉`"
					name += f" ​ `〈tier {result.get(tier_key, '?')}〉` 🎤{result.get(mic_key, '?')}"
					roster = "\n".join(
						"`{n}` {label}".format(n=n + 1, label=self._ranked_display(p, soracle_names.get(p.id) or get_nick(p)))
						for n, p in enumerate(t)
					) or self.m.gt("empty")
					embed.add_field(name=name, value=roster, inline=True)
			else:
				teams_names = [
					f"{t.emoji} ​ **{t.name}**" +
					(f" ​ `〈{self._team_avg_rating(t)}〉`" if self.m.ranked else "")
					for t in self.m.teams[:2]
				]
				team_players = [
					" ​ " +
					" ​ ".join([
						self._ranked_mention(p) for p in t
					])
					for t in self.m.teams[:2]
				]
				team_players[1] += "\n​"  # Extra empty line
				embed.add_field(name=teams_names[0], value=team_players[0], inline=False)
				embed.add_field(name=teams_names[1], value=team_players[1], inline=False)
			if self.m.ranked or self.m.cfg['pick_captains']:
				embed.add_field(
					name=self.m.gt("Captains"),
					value=" ​ " + join_and([self.m.teams[0][0].mention, self.m.teams[1][0].mention]),
					inline=False
				)
			if option:
				action_bits = []
				if self.m.ranked:
					action_bits.append(self.m.gt("{cmd} redo teams").format(cmd=f"`{self.m.qc.cfg.prefix}rebalance`"))
					action_bits.append(self.m.gt("{cmd} manual picks").format(cmd=f"`{self.m.qc.cfg.prefix}manual`"))
				action_bits.append(self.m.gt("more options at {url}").format(url=soracle.balancer_url()))
				embed.add_field(
					name="⚖️ " + (option.get('label') or self.m.gt("Perfect Balance")),
					value=" ​ · ​ ".join(action_bits) + "\n​",
					inline=False
				)

		else:  # just players list
			embed.add_field(
				name=self.m.gt("Players"),
				value=" \u200b " + " \u200b ".join((m.mention for m in self.m.players)),
				inline=False
			)
			if len(self.m.captains) and len(self.m.players) > 2:
				embed.add_field(
					name=self.m.gt("Captains"),
					value=" \u200b " + join_and([m.mention for m in self.m.captains]),
					inline=False
				)

		if len(self.m.maps):
			embed.add_field(
				name=self.m.qc.gt("Map" if len(self.m.maps) == 1 else "Maps"),
				value="\n".join((f"**{i}**" for i in self.m.maps)),
				inline=True
			)
		if self.m.cfg['server']:
			embed.add_field(name=self.m.qc.gt("Server"), value=f"`{self.m.cfg['server']}`", inline=True)

		if self.m.cfg['start_msg']:
			embed.add_field(name="—", value=self.m.cfg['start_msg'] + "\n\u200b", inline=False)

		if self.m.cfg['show_streamers']:
			if len(streamers := [p for p in self.m.players if isinstance(p.activity, Streaming)]):
				embed.add_field(name=self.m.qc.gt("Player streams"), inline=False, value="\n".join([
					f"{p.mention}: {p.activity.url}" for p in streamers
				]) + "\n\u200b")
		embed.set_footer(**self.footer)

		return embed
