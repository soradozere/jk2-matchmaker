# JK2 Matchmaker

A Discord matchmaking bot for the **Jedi Knight II: Jedi Outcast** CTF community — a fork of
[Leshaka/PUBobot2](https://github.com/Leshaka/PUBobot2) that adds deep integration with
[Soracle](https://soracle.vercel.app), the community's player database and team-balancing brain.

The bot deliberately contains **no balancing logic of its own**: team suggestions, player tiers,
role ratings and monthly stats all come from Soracle's API, so balance logic can evolve without
touching the bot.

## What this fork adds on top of PUBobot2

- **Soracle balance menu** — when a 12-player queue fills, the bot fetches three balanced team
  options (Perfect Balance / Fair Fight / Off-Role) and the captains pick via reactions:
  ✅ accept (both captains), 🔄 next option, ✋ manual picks. Configurable auto-accept timeout,
  and `/rebalance` returns a drafting match to the menu. Any failure (unlinked player, API down,
  wrong queue size) falls back to the untouched vanilla draft.
- **`/tier`** (also `=tier`) — a player's site profile: tier, role ratings, tooltip.
- **`/stats`** (also `=stats`) — month-to-date CTF stats from Soracle: matches, W/L, K/D, caps,
  returns, assists, base cleans, flag grabs, flag hold time. Vanilla's admin stats tools moved
  to `/stats_admin`.
- **`/friend`** (also `=friend`) — the team-mate you've won the most games alongside this month.
- **`/owneds`** (also `=owneds` / `=owned`) — two top-3 kill-matchup boards for the month: the
  opponents you out-frag the most across shared stat-tracked games, and the ones out-fragging you
  (total kill differential, min 2 shared games).
- **`/lastgame`** (also `=lg`) — in-depth view of the last match recorded on Soracle (score,
  winner, per-player final scores). Vanilla's last-game view is preserved on `/lastgame_vanilla`
  (`=lgv`).
- **Scoreboard auto-logging** — watches a channel for end-of-match `.csv` scoreboards and uploads
  them to Soracle's approval queue (only games with ≥12 distinct players). Set the channel(s) via
  the `SCOREBOARD_CHANNELS` config/env list (works for a dedicated channel — no pubobot-enable
  needed) or the per-channel `scoreboard_watch` setting. The owner is DM'd if an upload fails.
- **Reporting** — `=rl` reports a loss and nudges captains to log the game on Soracle. There are no
  player draw/abort commands; aborting is moderator-only via `/match report` (`abort`).
- **Classic Elo rating system** (`rating_system: Elo`) — team-average expected score, K=24,
  alongside vanilla's flat/Glicko2/TrueSkill options.
- **JK2 server watcher** — polls the community game servers over the Quake3 UDP protocol and
  pings the `@pug` role when a server crosses the player threshold (per-channel opt-in via the
  `pug_pings` setting). Supports ironman servers via their `ironmen` info key.
  Commands: `/servers`, `/pug`, `/pug_settings`.
- **Quality of life** — `=` prefix by default (jk2cpts muscle memory), last-come-wins `=capfor`,
  Red 🔥 vs Blue 💧 team defaults, leaderboard restricted to ranked channels.

Vanilla PUBobot2 commands work unchanged — see upstream's
[COMMANDS.md](https://github.com/Leshaka/PUBobot2/blob/main/COMMANDS.md).

## Running it

Requirements: **Python 3.12+**, **MySQL**, **gettext**.

```sh
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install cryptography   # required for MySQL 8 auth, not in upstream requirements
./compile_locales.sh
cp config.example.cfg config.cfg   # then fill in your tokens — config.cfg is gitignored
python3 PUBobot2.py
```

The Soracle integration needs `SORACLE_API_URL` and `SORACLE_API_SECRET` in `config.cfg`
(the secret must match `BOT_API_SECRET` in the Soracle deployment). Without them the bot
still runs as a normal PUBobot2.

Production runs on Railway: `railway.json` copies `config.railway.cfg` (environment-driven)
into place and starts the bot; pushes to `main` auto-deploy.

## Credits

All the heavy lifting — queues, drafts, ratings, check-ins, localisation — is
[PUBobot2](https://github.com/Leshaka/PUBobot2) by **Leshaka** (leshkajm@ya.ru).
If this bot is useful to you, consider [supporting upstream](https://boosty.to/leshaka).

Used libraries: [nextcord](https://github.com/nextcord/nextcord),
[aiomysql](https://github.com/aio-libs/aiomysql), [emoji](https://github.com/carpedm20/emoji/),
[glicko2](https://github.com/deepy/glicko2), [TrueSkill](https://trueskill.org/),
[prettytable](https://github.com/jazzband/prettytable).

## License

Copyright (C) 2020 **Leshaka**.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License version 3 as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

See 'GNU GPLv3.txt' for GNU General Public License.
