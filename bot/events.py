import asyncio
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


# How long a CSV-only message waits for a same-channel JSON before uploading
# anyway — see the note in handle_scoreboard_attachments. Every real pair
# observed on Soracle landed ~6s apart, so this leaves generous margin without
# meaningfully delaying a match on the (currently unseen) night Tom's bot only
# manages the CSV.
CSV_HOLD_SECONDS = 20

# channel_id -> the asyncio.Task currently holding a CSV upload back in case a
# JSON for the same match is still in flight. Only the most recently held CSV
# per channel is tracked — if a second un-JSON'd CSV lands in the same channel
# before the first one's hold expires, a JSON arriving after that would cancel
# the wrong one. Not worth guarding against: matches in one channel are spaced
# by minutes to hours in practice, never seconds.
_pending_csv_uploads = {}


async def _upload_scoreboard(attachment, message, where):
	""" Read one attachment and forward it to Soracle, DMing the owner on any
		failure so a match can't silently vanish. """
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
		return
	except Exception as e:
		log.error(f"Unexpected error uploading scoreboard '{attachment.filename}': {e}")
		await _dm_owner(f"⚠️ Error uploading scoreboard `{attachment.filename}` ({where}): {e}")
		return

	log.info(f"Scoreboard '{attachment.filename}' -> Soracle: HTTP {status} {data}")
	# 200 = queued / skipped (<12) / duplicate — all fine. >=400 means Soracle
	# rejected it (unparseable, auth, server error), which warrants a heads-up.
	if status >= 400:
		await _dm_owner(
			f"⚠️ The stats site rejected scoreboard `{attachment.filename}` ({where}) — "
			f"HTTP {status}: {data}. The file is still in the channel."
		)


async def _upload_csv_after_delay(channel_id, attachment, message, where):
	try:
		await asyncio.sleep(CSV_HOLD_SECONDS)
	except asyncio.CancelledError:
		return  # a JSON for this channel showed up and won instead
	_pending_csv_uploads.pop(channel_id, None)
	await _upload_scoreboard(attachment, message, where)


async def handle_scoreboard_attachments(message):
	if not _is_scoreboard_channel(message):
		return

	where = f"#{getattr(message.channel, 'name', '?')}"
	if message.guild:
		where = f"{message.guild.name} > {where}"

	json_atts = [a for a in message.attachments if a.filename.lower().endswith('.json')]
	csv_atts = [a for a in message.attachments if a.filename.lower().endswith('.csv')]
	if not json_atts and not csv_atts:
		return

	channel_id = message.channel.id

	if json_atts:
		# JSON wins outright — whether it arrived on THIS message alongside a CSV
		# (already handled: only json_atts gets uploaded below), or as its own
		# separate message a few seconds after a CSV-only one already started its
		# hold in this channel (cancel that hold so the CSV never uploads).
		held = _pending_csv_uploads.pop(channel_id, None)
		if held:
			held.cancel()
		for attachment in json_atts:
			await _upload_scoreboard(attachment, message, where)
		return

	# CSV only, no JSON on this message. Tom's bot posts the JSON as a SEPARATE
	# Discord message a few seconds later (confirmed from Soracle's pending-match
	# timestamps — they carry different message ids, not one message with two
	# attachments), so uploading immediately would race it: Soracle's dedup keys
	# on Discord message id, which differs between the two messages, so both
	# would land as separate pending matches instead of the second being caught
	# as a duplicate. Hold briefly so the JSON — better data: true duration, the
	# per-opponent kill/return matrix, TELE kills — can pre-empt it if it's on
	# its way.
	for attachment in csv_atts:
		task = asyncio.create_task(_upload_csv_after_delay(channel_id, attachment, message, where))
		_pending_csv_uploads[channel_id] = task


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
async def on_member_join(member):
	await bot.welcome.on_join(member)


@dc.event
async def on_member_remove(member):
	for qc in filter(lambda i: i.id == member.guild.id, bot.queue_channels.values()):
		await qc.remove_members(member, reason="left guild")
	await bot.welcome.on_leave(member)
