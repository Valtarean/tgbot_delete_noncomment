from datetime import datetime, timezone
from typing import Optional, Dict, Any
import html
import logging

from aiogram import Bot
from aiogram.types import Message

from db import set_last_warning, get_all_warnings

logger = logging.getLogger(__name__)


class WarningManager:
    def __init__(
        self,
        cooldown_seconds: int = 180,
        db_path: str = "data/bot.sqlite3",
        message_template: Optional[str] = None,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.db_path = db_path
        # in-memory cache to reduce DB hits (user_id -> timestamp int)
        self._cache: Dict[int, int] = {}
        # template string; may include placeholders {username}, {full_name}, {chat_id}, {message_id}
        self.message_template = message_template or (
            "Похоже {username}, вы пишете в общем чате, тогда как Ваш ответ "
            "должен быть записан как комментарий под постом.\n\n"
            "Перенесите сообщение в комментарии под соответствующим постом."
        )

    async def _load_cache(self):
        try:
            data = await get_all_warnings(self.db_path)
            self._cache = data
        except Exception:
            logger.exception("Failed to load warnings cache")

    async def can_warn(self, user_id: int) -> bool:
        if not self._cache:
            await self._load_cache()
        ts = self._cache.get(user_id)
        if not ts:
            return True
        now = int(datetime.now(timezone.utc).timestamp())
        return (now - ts) >= self.cooldown_seconds

    async def record_warning(self, user_id: int) -> None:
        now = int(datetime.now(timezone.utc).timestamp())
        await set_last_warning(self.db_path, user_id, now)
        self._cache[user_id] = now

    async def get_time_until_next_warning(self, user_id: int) -> Optional[int]:
        if not self._cache:
            await self._load_cache()
        ts = self._cache.get(user_id)
        if not ts:
            return None
        now = int(datetime.now(timezone.utc).timestamp())
        remaining = self.cooldown_seconds - (now - ts)
        return max(0, remaining) if remaining > 0 else None

    def _render_message(self, user: Any, chat_id: int, message_id: int) -> str:
        # safe substitutions
        if user:
            if getattr(user, "username", None):
                username = f"@{user.username}"
            else:
                # escape full_name if username missing
                username = html.escape(getattr(user, "full_name", ""))
            full_name = html.escape(getattr(user, "full_name", ""))
        else:
            username = "Пользователь"
            full_name = "Unknown"

        try:
            return self.message_template.format(
                username=username,
                full_name=full_name,
                chat_id=chat_id,
                message_id=message_id,
            )
        except Exception:
            logger.exception("Failed to render warning message template; falling back to default")
            # fallback: simple escaped message
            return html.escape(
                f"Пожалуйста, переместите сообщение #{message_id} в комментарии под соответствующим постом."
            )

    async def send_warning(self, bot: Bot, message: Message) -> Optional[int]:
        user = message.from_user
        if not user:
            return None
        user_id = user.id
        if not await self.can_warn(user_id):
            remaining = await self.get_time_until_next_warning(user_id)
            logger.info("Not sending warning to %s, cooldown %s", user_id, remaining)
            return None

        text = self._render_message(user, message.chat.id, message.message_id)
        try:
            sent = await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                reply_to_message_id=message.message_id,
                parse_mode="HTML",
            )
            await self.record_warning(user_id)
            logger.info("Warning sent to %s", user_id)
            return sent.message_id
        except Exception:
            logger.exception("Failed to send warning")
            return None

    async def format_stats(self) -> str:
        if not self._cache:
            await self._load_cache()
        if not self._cache:
            return "📊 <b>Статистика предупреждений</b>\n\nПредупреждений пока не было."
        lines = ["📊 <b>Статистика предупреждений</b>\n"]
        now = int(datetime.now(timezone.utc).timestamp())
        for user_id, ts in sorted(self._cache.items(), key=lambda x: x[1], reverse=True):
            elapsed = now - ts
            if elapsed < 60:
                time_str = f"{int(elapsed)}с назад"
            elif elapsed < 3600:
                time_str = f"{int(elapsed // 60)}м назад"
            else:
                time_str = f"{int(elapsed // 3600)}ч назад"
            remaining = self.cooldown_seconds - elapsed
            status = f"⏳ {remaining}s" if remaining > 0 else "✅ доступно"
            lines.append(f"👤 ID <code>{user_id}</code>: {time_str} [{status}]")
        lines.append(f"\n⏱ Cooldown: {self.cooldown_seconds}s")
        return "\n".join(lines)