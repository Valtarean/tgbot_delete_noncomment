import html
import logging
from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot, admin_id: int, group_id: int):
        self.bot = bot
        self.admin_id = admin_id
        self.group_id = group_id

    async def send_startup(self):
        try:
            await self.bot.send_message(
                self.admin_id,
                "🟢 <b>Бот запущен</b>\n\nНачат мониторинг сообщений вне веток обсуждения канала.",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to send startup notification")

    async def send_shutdown(self):
        try:
            await self.bot.send_message(self.admin_id, "🔴 <b>Бот остановлен</b>", parse_mode="HTML")
        except Exception:
            logger.exception("Failed to send shutdown notification")

    async def notify_off_topic_message(self, message: Message):
        user = message.from_user
        text = (message.text or message.caption or "").strip()
        chat_id_str = str(self.group_id)
        clean_id = chat_id_str[4:] if chat_id_str.startswith("-100") else chat_id_str
        message_link = f"https://t.me/c/{clean_id}/{message.message_id}"
        name = html.escape(user.full_name) if user else "Unknown"
        notification = (
            "⚠️ <b>Сообщение вне ветки обсуждения</b>\n\n"
            f"👤 <b>Пользователь:</b> {name}"
        )
        if user and user.username:
            notification += f" (@{html.escape(user.username)})"
        safe_text = html.escape(text[:200]) if text else "⚠️ Медиа без текста"
        notification += (
            f"\n💬 <b>Текст:</b> {safe_text}"
            f"{'...' if len(text) > 200 else ''}\n"
            f"🔗 <b>Ссылка:</b> <a href='{message_link}'>Сообщение #{message.message_id}</a>"
        )
        try:
            await self.bot.send_message(self.admin_id, notification, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.exception("Failed to send admin notification")