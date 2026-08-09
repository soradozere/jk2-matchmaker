import traceback
from nextcord import ChannelType, Activity, ActivityType

from core.client import dc
from core.console import log
from core.config import cfg
import bot
from bot import soracle


@dc.event
async def on_init():
	await bot.stats.check_match_id_counter()


@dc.event
async def on_think(frame_time):
	for match in bot.active_matches:
		try:
			await match.think(frame_time)
		except Exception as e:
			log.error("\n".join([
				f"Error at Match.think().",
				f"match_id: {match.id}).",
				f"{str(e)}. Traceback:\n{traceback.format_exc()}=========="
			]))
			bot.active_matches.remove(match)
			break
	await bot.expire.think(frame_time)
	await bot.noadds.think(frame_time)
	await bot.stats.jobs.think(frame_time)
	await bot.expire_auto_ready(frame_time)
	await bot.jk2_servers.think(frame_time)
	await bot.wrapped.think(frame_time)


# Forward end-of-match scoreboard CSVs posted in a watched channel to Soracle's
# approval queue. Normal outcomes are silent (admins review on the site); only
# failures (Soracle unreachable / rejected the upload) DM the owner so a match
# can't silently vanish.
#
# A channel is watched if it's listed in cfg.SCOREBOARD_CHANNELS (a plain,
# dedicated channel — no pubobot-enable needed) OR it's a pubobot channel with
# the 'scoreboard_watch' setting on.
def _is_scoreboard_channel(message):
	if not soracle.enabled():
		return False
	if message.channel.id in getattr(cfg, 'SCOREBOARD_CHANNELS', []):
		return True
	qc = bot.queue_channels.get(message.channel.id)
	return qc is not None and getattr(qc.cfg, 'scoreboard_watch', False)


async def _dm_owner(text):
	""" Best-effort DM to the bot owner (DC_OWNER_ID). Used to flag scoreboard
		uploads that didn't reach Soracle, so a match can't silently vanish. """
	try:
		owner = dc.get_user(cfg.DC_OWNER_ID) or await dc.fetch_user(cfg.DC_OWNER_ID)
		if owner:
			await owner.send(text[:1900])
	except Exception as e:
		log.error(f"Could not DM owner: {e}")


async def handle_scoreboard_attachments(message):
	if not _is_scoreboard_channel(message):
		return

	where = f"#{getattr(message.channel, 'name', '?')}"
	if message.guild:
		where = f"{message.guild.name} > {where}"

	# Tom's scoreboard bot posts the SAME match as both .json and .csv. Prefer the
	# JSON: it carries everything the CSV does plus match duration, per-opponent
	# kill/return matrix and TELE kills. Uploading both would be worse than
	# arbitrary — they share a Discord message id, so Soracle's idempotency check
	# rejects whichever lands second, making the winner a race.
	scoreboards = [a for a in message.attachments if a.filename.lower().endswith('.json')]
	if not scoreboards:
		scoreboards = [a for a in message.attachments if a.filename.lower().endswith('.csv')]

	for attachment in scoreboards:
		try:
			payload_bytes = await attachment.read()
			status, data = await soracle.upload_scoreboard(
				payload_bytes, attachment.filename,
				guild_id=message.guild.id if message.guild else None,
				channel_id=message.channel.id,
				message_id=message.id,
				user_id=message.author.id,
				username=str(message.author),
			)
		except soracle.SoracleError as e:
			log.error(f"Failed to upload scoreboard '{attachment.filename}' to Soracle: {e}")
			await _dm_owner(
				f"⚠️ Couldn't reach the stats site to upload scoreboard `{attachment.filename}` "
				f"({where}). The file is still in the channel — re-post it once the site is back."
			)
			continue
		except Exception as e:
			log.error(f"Unexpected error uploading scoreboard '{attachment.filename}': {e}")
			await _dm_owner(f"⚠️ Error uploading scoreboard `{attachment.filename}` ({where}): {e}")
			continue

		log.info(f"Scoreboard '{attachment.filename}' -> Soracle: HTTP {status} {data}")
		# 200 = queued / skipped (<12) / duplicate — all fine. >=400 means Soracle
		# rejected it (unparseable, auth, server error), which warrants a heads-up.
		if status >= 400:
			await _dm_owner(
				f"⚠️ The stats site rejected scoreboard `{attachment.filename}` ({where}) — "
				f"HTTP {status}: {data}. The file is still in the channel."
			)


@dc.event
async def on_message(message):
	if message.channel.type == ChannelType.private and message.author.id != dc.user.id:
		await message.channel.send(cfg.HELP)

	if message.channel.type != ChannelType.text:
		return

	if message.content == '!enable_pubobot':
		await bot.enable_channel(message)
	elif message.content == '!disable_pubobot':
		await bot.disable_channel(message)

	if message.attachments and message.author.id != dc.user.id:
		await handle_scoreboard_attachments(message)


@dc.event
async def on_reaction_add(reaction, user):
	if user.id != dc.user.id and reaction.message.id in bot.waiting_reactions.keys():
		await bot.waiting_reactions[reaction.message.id](reaction, user)


@dc.event
async def on_reaction_remove(reaction, user):  # FIXME: this event does not get triggered for some reason
	if user.id != dc.user.id and reaction.message.channel.id in bot.waiting_reactions.keys():
		await bot.waiting_reactions[reaction.message.id](reaction, user, remove=True)


@dc.event
async def on_ready():
	await dc.change_presence(activity=Activity(type=ActivityType.watching, name=cfg.STATUS))
	if not bot.bot_was_ready:  # Connected for the first time, load everything
		log.info(f"Logged in discord as '{dc.user.name}#{dc.user.discriminator}'.")
		log.info("Loading queue channels...")
		for channel_id in await bot.QueueChannel.cfg_factory.p_keys():
			channel = dc.get_channel(channel_id)
			if channel:
				bot.queue_channels[channel_id] = await bot.QueueChannel.create(channel)
				await bot.queue_channels[channel_id].update_info(channel)
				log.info(f"\tInit channel {channel.guild.name}>#{channel.name} successful.")
			else:
				log.info(f"\tCould not reach a text channel with id {channel_id}.")

		await bot.load_state()
		bot.bot_was_ready = True
		bot.bot_ready = True
		log.info("Done.")
	else:  # Reconnected, fetch new channel objects
		bot.bot_ready = True
		log.info("Reconnected to discord.")


@dc.event
async def on_disconnect():
	log.info("Connection to discord is lost.")
	bot.bot_ready = False


@dc.event
async def on_resumed():
	log.info("Connection to discord is resumed.")
	if bot.bot_was_ready:
		bot.bot_ready = True


@dc.event
async def on_presence_update(before, after):
	if after.raw_status not in ['idle', 'offline']:
		return
	if after.id in bot.allow_offline:
		return

	for qc in filter(lambda i: i.guild_id == after.guild.id, bot.queue_channels.values()):
		if after.raw_status == "offline" and qc.cfg.remove_offline:
			await qc.remove_members(after, reason="offline")

		if after.raw_status == "idle" and qc.cfg.remove_afk and bot.expire.get(qc, after) is None:
			await qc.remove_members(after, reason="afk", highlight=True)


@dc.event
async def on_member_remove(member):
	for qc in filter(lambda i: i.id == member.guild.id, bot.queue_channels.values()):
		await qc.remove_members(member, reason="left guild")
