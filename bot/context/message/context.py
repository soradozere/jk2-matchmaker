from nextcord import Message, Embed, Forbidden

from bot import QueueChannel
from core.utils import error_embed, ok_embed

from ..context import Context


class MessageContext(Context):
	""" Context for the text message commands """

	def __init__(self, qc: QueueChannel, message: Message):
		self.message = message
		super().__init__(qc, message.channel, message.author)

	async def reply(self, content: str = None, embed: Embed = None):
		await self.message.reply(content=content, embed=embed)

	async def notice(self, content: str = None, embed: Embed = None):
		await (self.message.thread or self.message.channel).send(content=content, embed=embed)

	async def reply_dm(self, content: str = None, embed: Embed = None):
		try:
			await self.author.send(content=content, embed=embed)
		except Forbidden:
			# DMs closed — a per-server Discord privacy setting, or the bot got blocked.
			# Fall back to a public reply so the command still does something useful
			# instead of silently doing nothing (or crashing, pre-fix).
			note = "*(Couldn't DM you — your Discord privacy settings block messages from server members. Posting here instead.)*"
			await self.message.reply(content=f"{note}\n{content}" if content else note, embed=embed)

	async def error(self, *args, **kwargs):
		await self.message.reply(embed=error_embed(*args, **kwargs))

	async def success(self, *args, **kwargs):
		await self.message.reply(embed=ok_embed(*args, **kwargs))