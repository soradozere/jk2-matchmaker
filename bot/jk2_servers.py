# -*- coding: utf-8 -*-
""" JK2 game server watcher, ported from jk2-pug-bot.
	Polls servers over the Quake3 UDP protocol from the think loop, pings the
	@pug role in opted-in queue channels (channel cfg 'pug_pings') when a server
	crosses the player threshold, and powers the =servers / =pug commands.
	Servers running the ironman mode report an 'ironmen' info key — when present
	it overrides the player count. """

import asyncio
import socket
from time import time

from nextcord import DiscordException
from nextcord.utils import get as dc_get

import bot
from core.client import dc
from core.console import log

PUG_ROLE_NAME = "pug"
PLAYER_THRESHOLD = 5
POLL_INTERVAL = 5 * 60
PING_COOLDOWN = 240 * 60  # per server
IGNORED_NAME_PREFIXES = ["pidi"]  # spectator bots (Pidi/Pidiwin); "Pada*" is usually a default-named human

SERVERS = [
	dict(name="NA East", host="192.223.24.74", port=28070),
	dict(name=":: DOZER NY NWH ::", host="199.19.72.85", port=28070),
	dict(name="The American NWH", host="74.91.115.117", port=28070),
	dict(name="POMMESBUDE [CTF]", host="141.144.226.30", port=28070),
	dict(name="NWH Tokyo", host="54.238.175.102", port=28070),
	dict(name="slowburn/freedom #defrag", host="176.103.220.40", port=28070),
]

_was_above = {}  # "host:port" -> bool
_last_ping_at = {}  # "host:port" -> timestamp
_next_poll_at = 0
_poll_task = None


def _strip_colors(name):
	clean, i = "", 0
	while i < len(name):
		if name[i] == "^" and i + 1 < len(name):
			i += 2
		else:
			clean += name[i]
			i += 1
	return clean.strip("^ ")


def query_server(host, port, timeout=3.0):
	""" Blocking UDP getstatus query — run via asyncio.to_thread. """
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.settimeout(timeout)
		sock.sendto(b"\xff\xff\xff\xffgetstatus\x00", (host, port))
		data, _ = sock.recvfrom(4096)
		sock.close()

		decoded = data[4:].decode("utf-8", errors="replace")
		if not decoded.startswith("statusResponse"):
			return dict(online=False)

		lines = decoded.split("\n")
		info_parts = (lines[1] if len(lines) > 1 else "").strip("\\").split("\\")
		info = {}
		for i in range(0, len(info_parts) - 1, 2):
			info[info_parts[i]] = info_parts[i + 1]

		players = []
		for line in lines[2:]:
			line = line.strip()
			if not line:
				continue
			parts = line.split(" ", 2)
			if len(parts) >= 3:
				players.append(_strip_colors(parts[2].strip('"')))

		real_players = [
			p for p in players
			if not any(p.lower().startswith(prefix.lower()) for prefix in IGNORED_NAME_PREFIXES)
		]

		# Ironman servers publish an 'ironmen' count which overrides the player list
		ironmen = None
		if "ironmen" in info:
			try:
				ironmen = int(info["ironmen"])
			except ValueError:
				pass

		return dict(
			online=True,
			players=real_players,
			count=ironmen if ironmen is not None else len(real_players),
			ironman=ironmen is not None,
			map=info.get("mapname", info.get("sv_mapname", "unknown")),
			hostname=_strip_colors(info.get("sv_hostname", "")),
			max_players=int(info.get("sv_maxclients", 32)),
		)
	except Exception:
		return dict(online=False)


async def query_all():
	results = await asyncio.gather(*(
		asyncio.to_thread(query_server, s["host"], s["port"]) for s in SERVERS
	))
	return list(zip(SERVERS, results))


async def think(frame_time):
	global _next_poll_at, _poll_task
	if frame_time < _next_poll_at:
		return
	_next_poll_at = frame_time + POLL_INTERVAL
	if _poll_task and not _poll_task.done():
		return  # previous poll still running
	_poll_task = asyncio.get_event_loop().create_task(_poll())


async def _poll():
	try:
		now = int(time())
		channels = [
			channel for qc in bot.queue_channels.values()
			if qc.cfg.pug_pings and (channel := dc.get_channel(qc.id)) is not None
		]

		for server, data in await query_all():
			key = f"{server['host']}:{server['port']}"
			above = data.get("online", False) and data["count"] >= PLAYER_THRESHOLD
			previously_above = _was_above.get(key)
			_was_above[key] = above

			if not (above and not previously_above):
				continue
			if (last := _last_ping_at.get(key)) and now - last < PING_COOLDOWN:
				log.debug(f"JK2 servers: {server['name']} above threshold but on ping cooldown.")
				continue
			if not channels:
				continue

			_last_ping_at[key] = now
			count_str = f"{data['count']} ironmen" if data['ironman'] else f"{data['count']} players"
			player_list = ", ".join(data["players"]) if data["players"] else "players unknown"

			for channel in channels:
				role = dc_get(channel.guild.roles, name=PUG_ROLE_NAME)
				msg = (
					f"{role.mention if role else '@' + PUG_ROLE_NAME} "
					f"**{count_str} on {server['name']}** — join up!\n"
					f"🗺️ Map: `{data['map']}` | 👥 {player_list}\n"
					f"```connect {server['host']}:{server['port']}```"
				)
				try:
					await channel.send(msg)
				except DiscordException as e:
					log.error(f"JK2 servers: failed to ping in #{channel.name}: {str(e)}")

			log.info(f"JK2 servers: pinged for {server['name']} ({count_str}) in {len(channels)} channel(s).")
	except Exception as e:
		import traceback
		log.error(f"JK2 servers poll failed: {str(e)}\n{traceback.format_exc()}")


def status_lines(results):
	""" Embed-description lines, busiest servers first, offline last. """
	results = sorted(
		results,
		key=lambda r: (not r[1].get("online"), -(r[1].get("count", 0) if r[1].get("online") else 0))
	)
	lines = []
	for server, data in results:
		if not data.get("online"):
			lines.append(f"🔴 ​ **{server['name']}** — offline")
			continue
		indicator = "🟢" if data["count"] >= PLAYER_THRESHOLD else ("🟡" if data["count"] else "⚪")
		count_str = f"**{data['count']}** ironmen" if data["ironman"] else f"**{data['count']}**/{data['max_players']}"
		lines.append(f"{indicator} ​ **{server['name']}** ​ {count_str} ​ · ​ `{data['map']}`")
		if data["players"]:
			lines.append(f"> -# {', '.join(data['players'])} ​ · ​ `connect {server['host']}:{server['port']}`")
	return lines
