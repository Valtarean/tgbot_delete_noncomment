from typing import Optional
from aiogram.types import Message

TELEGRAM_SERVICE_ID = 777000


class MessageAnalyzer:
    def __init__(self, settings):
        self.settings = settings

    def is_channel_post(self, message: Message) -> bool:
        # robust checks for channel-origin or forwarded-from-channel
        try:
            if getattr(message, "sender_chat", None):
                return True
            if message.from_user and getattr(message.from_user, "id", None) == TELEGRAM_SERVICE_ID:
                return True
            if getattr(message, "is_automatic_forward", False):
                return True
            fchat = getattr(message, "forward_from_chat", None)
            if fchat and getattr(fchat, "id", None) == self.settings.channel_id:
                return True
            origin = getattr(message, "forward_origin", None)
            if origin and getattr(origin, "chat", None) and getattr(origin.chat, "id", None) == self.settings.channel_id:
                return True
        except Exception:
            # be permissive in case of unexpected structure
            return False
        return False

    async def is_in_discussion_thread(self, message: Message) -> bool:
        if self.is_channel_post(message):
            return True
        if getattr(message, "message_thread_id", None):
            return True
        return await self._check_reply_chain(message, depth=0)

    async def _check_reply_chain(self, message: Message, depth: int) -> bool:
        if depth >= self.settings.max_chain_depth:
            return False
        reply = getattr(message, "reply_to_message", None)
        if not reply:
            return False
        if self.is_channel_post(reply):
            return True
        if getattr(reply, "message_thread_id", None):
            return True
        if getattr(reply, "reply_to_message", None):
            return await self._check_reply_chain(reply, depth + 1)
        return False

    async def analyze_chain(self, message: Message, max_depth: int = 10) -> str:
        return await self._analyze_recursive(message, 0, max_depth)

    async def _analyze_recursive(self, message: Message, depth: int, max_depth: int) -> str:
        if depth >= max_depth:
            return f"{'  '*depth}⚡ reached max depth"
        indent = "  " * depth
        parts = []
        thread_info = f" [thread: {getattr(message, 'message_thread_id', '')}]" if getattr(message, "message_thread_id", None) else ""
        user_info = f" from {getattr(getattr(message, 'from_user', None), 'id', 'N/A')}"
        parts.append(f"{indent}Level {depth}: id {getattr(message, 'message_id', 'N/A')}{user_info}{thread_info}")
        if self.is_channel_post(message):
            parts.append(f"{indent}   CHANNEL POST")
        if getattr(message, "reply_to_message", None):
            reply = message.reply_to_message
            parts.append(f"{indent}   reply to: {getattr(reply, 'message_id', 'N/A')}")
            parts.append(await self._analyze_recursive(reply, depth + 1, max_depth))
        else:
            parts.append(f"{indent}   END")
        return "\n".join(parts)