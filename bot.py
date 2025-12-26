#!/usr/bin/env python3
import asyncio
import logging
import signal
import sys
from typing import Optional, Set, List, Any, Coroutine

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.filters import Command

from settings import Settings
from analyzer import MessageAnalyzer
from notifier import NotificationService
from warning_manager import WarningManager
from db import init_db

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


class DiscussionBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bot = Bot(token=self.settings.bot_token)
        self.dp = Dispatcher()
        self.analyzer = MessageAnalyzer(settings)
        self.notifier = NotificationService(self.bot, settings.admin_id, settings.group_id)
        self.warning_manager = WarningManager(
            cooldown_seconds=self.settings.warning_cooldown,
            db_path=self.settings.db_path,
        )
        self._admin_cache: Set[int] = set()
        self._admin_cache_time = None
        self._admin_cache_ttl = self.settings.admin_cache_ttl_minutes
        self._tasks: Set[asyncio.Task] = set()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.dp.message.register(
            self._handle_group_message,
            F.chat.id == self.settings.group_id,
        )
        self.dp.message.register(self._cmd_status, Command("status"))
        self.dp.message.register(self._cmd_test, Command("test"))
        self.dp.message.register(self._cmd_debug, Command("debug_chain"))
        self.dp.message.register(self._cmd_warnings, Command("warnings"))
        self.dp.message.register(
            self._handle_private_message, F.chat.type == ChatType.PRIVATE
        )

    async def _get_admin_user_ids_cached(self):
        # Minimal cache: refresh every admin_cache_ttl_minutes
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if self._admin_cache_time and (now - self._admin_cache_time).total_seconds() < (
            self._admin_cache_ttl * 60
        ):
            return self._admin_cache
        try:
            admins = await self.bot.get_chat_administrators(chat_id=self.settings.group_id)
            self._admin_cache = {admin.user.id for admin in admins if admin.user}
            self._admin_cache_time = now
            logger.debug("Admin cache refreshed: %d admins", len(self._admin_cache))
            return self._admin_cache
        except Exception:
            logger.exception("Failed to refresh admin list")
            return self._admin_cache

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)

        def _on_done(t: asyncio.Task):
            self._tasks.discard(t)
            if t.cancelled():
                logger.debug("Background task cancelled")
            else:
                try:
                    exc = t.exception()
                    if exc:
                        logger.exception("Background task exception", exc_info=exc)
                except asyncio.CancelledError:
                    # task was cancelled while getting exception
                    pass

        task.add_done_callback(_on_done)
        return task

    async def _schedule_deletion(self, chat_id: int, message_ids: List[int], delay: int):
        try:
            await asyncio.sleep(delay)
            for mid in message_ids:
                try:
                    await self.bot.delete_message(chat_id=chat_id, message_id=mid)
                    logger.debug("Deleted message %s", mid)
                except Exception:
                    logger.debug("Failed to delete message %s", mid, exc_info=True)
        except asyncio.CancelledError:
            logger.info("Deletion task cancelled")
            raise
        except Exception:
            logger.exception("Error in deletion task")

    async def _handle_group_message(self, message: Message) -> None:
        # Ignore admins
        if message.from_user:
            admin_ids = await self._get_admin_user_ids_cached()
            if message.from_user.id in admin_ids:
                logger.debug("Message from admin %s skipped", message.from_user.id)
                return

        full_text = (message.text or message.caption or "").strip()
        if full_text.startswith("/"):
            return

        if self._is_service_message(message):
            logger.debug("Service message ignored: %s", getattr(message, "message_id", None))
            return

        is_in_thread = await self.analyzer.is_in_discussion_thread(message)
        logger.info(
            "New group message id=%s user=%s in_thread=%s",
            getattr(message, "message_id", None),
            getattr(getattr(message, "from_user", None), "id", None),
            is_in_thread,
        )

        if not is_in_thread:
            warning_id = await self.warning_manager.send_warning(self.bot, message)
            await self.notifier.notify_off_topic_message(message)

            to_delete = [message.message_id]
            if warning_id:
                to_delete.append(warning_id)

            self._create_task(
                self._schedule_deletion(
                    chat_id=message.chat.id,
                    message_ids=to_delete,
                    delay=self.settings.auto_delete_delay,
                )
            )
        else:
            logger.debug("Message is in discussion thread or from channel; ignored")

    @staticmethod
    def _is_service_message(message: Message) -> bool:
        service_fields = [
            "new_chat_members",
            "left_chat_member",
            "new_chat_title",
            "new_chat_photo",
            "delete_chat_photo",
            "group_chat_created",
            "supergroup_chat_created",
            "channel_chat_created",
            "migrate_to_chat_id",
            "migrate_from_chat_id",
            "pinned_message",
            "invoice",
            "successful_payment",
            "video_chat_started",
            "video_chat_ended",
            "video_chat_scheduled",
            "video_chat_participants_invited",
            "web_app_data",
            "forum_topic_created",
            "forum_topic_edited",
            "forum_topic_closed",
            "forum_topic_reopened",
            "general_forum_topic_hidden",
            "general_forum_topic_unhidden",
            "write_access_allowed",
        ]
        return any(getattr(message, f, None) is not None for f in service_fields)

    async def _cmd_status(self, message: Message) -> None:
        if not message.from_user or message.from_user.id != self.settings.admin_id:
            return
        await message.answer(
            "🟢 <b>Статус бота</b>\n\n"
            f"📊 Группа: <code>{self.settings.group_id}</code>\n"
            f"📺 Канал: <code>{self.settings.channel_id}</code>\n"
            f"👤 Админ: <code>{self.settings.admin_id}</code>\n"
            f"⏱ Удаление через: <code>{self.settings.auto_delete_delay}s</code>",
            parse_mode="HTML",
        )

    async def _cmd_test(self, message: Message) -> None:
        await message.answer(
            "✅ <b>Бот работает!</b>\n\n"
            "Администраторы игнорируются.\n"
            "Сообщения вне веток удаляются автоматически.",
            parse_mode="HTML",
        )

    async def _cmd_debug(self, message: Message) -> None:
        if not message.from_user or message.from_user.id != self.settings.admin_id:
            return
        if not message.reply_to_message:
            await message.answer("❌ Ответьте на сообщение для анализа цепочки.")
            return
        chain_info = await self.analyzer.analyze_chain(message.reply_to_message)
        await message.answer(f"<pre>{chain_info}</pre>", parse_mode="HTML")

    async def _cmd_warnings(self, message: Message) -> None:
        if not message.from_user or message.from_user.id != self.settings.admin_id:
            return
        stats = await self.warning_manager.format_stats()
        await message.answer(stats, parse_mode="HTML")

    async def _handle_private_message(self, message: Message) -> None:
        await message.answer(
            "👋 Привет!\n\n"
            "Я отслеживаю сообщения в группе обсуждения канала.\n"
            "Команды: /status /test /debug_chain /warnings"
        )

    async def start(self) -> None:
        logger.info("Starting bot...")
        await self.notifier.send_startup()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))
            except NotImplementedError:
                # Windows may raise
                pass

        try:
            await self.dp.start_polling(self.bot)
        except Exception:
            logger.exception("Polling error")
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("Shutting down...")
        # cancel background tasks
        for t in list(self._tasks):
            t.cancel()
        await asyncio.sleep(0.1)
        await self.notifier.send_shutdown()
        try:
            await self.bot.session.close()
        except Exception:
            logger.exception("Error closing bot session")
        logger.info("Shutdown complete")


async def main():
    try:
        settings = Settings()
    except Exception as exc:
        logger.critical("Settings error: %s", exc)
        sys.exit(1)

    # init DB for warnings
    await init_db(settings.db_path)

    bot = DiscussionBot(settings)
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())