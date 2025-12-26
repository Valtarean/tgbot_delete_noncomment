import asyncio
import os
import sys
import logging
from typing import Optional, Dict, List, Set
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatType
from aiogram.filters import Command
from dotenv import load_dotenv


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Константа для системного аккаунта Telegram
TELEGRAM_SERVICE_ID = 777000

# Время кэширования списка администраторов (в минутах)
ADMIN_CACHE_TTL_MINUTES = 600


@dataclass
class BotConfig:
    """Конфигурация бота"""
    token: str
    admin_id: int
    group_id: int
    channel_id: int
    max_chain_depth: int = 20
    auto_delete_delay: int = 10  # секунд

    @classmethod
    def from_env(cls) -> 'BotConfig':
        load_dotenv()
        required_vars = ['BOT_TOKEN', 'ADMIN_ID', 'GROUP_ID', 'CHANNEL_ID']
        env_values = {var: os.getenv(var) for var in required_vars}

        missing = [var for var, value in env_values.items() if not value]
        if missing:
            raise ValueError(
                f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}\n"
                f"Проверьте файл .env"
            )

        try:
            auto_delete_delay = int(os.getenv('AUTO_DELETE_DELAY', '10'))
        except ValueError:
            auto_delete_delay = 10

        try:
            return cls(
                token=env_values['BOT_TOKEN'],
                admin_id=int(env_values['ADMIN_ID']),
                group_id=int(env_values['GROUP_ID']),
                channel_id=int(env_values['CHANNEL_ID']),
                auto_delete_delay=auto_delete_delay
            )
        except ValueError as e:
            raise ValueError(f"ID должны быть целыми числами: {e}")


class MessageAnalyzer:
    """Анализатор сообщений для определения принадлежности к веткам обсуждения"""

    def __init__(self, config: BotConfig):
        self.config = config

    def is_channel_post(self, message: Message) -> bool:
        if message.from_user and message.from_user.id == TELEGRAM_SERVICE_ID:
            return True
        if getattr(message, 'is_automatic_forward', False):
            return True
        if (message.forward_from_chat and
                message.forward_from_chat.id == self.config.channel_id):
            return True
        if hasattr(message, 'forward_origin'):
            origin = message.forward_origin
            if hasattr(origin, 'chat') and origin.chat.id == self.config.channel_id:
                return True
        return False

    async def is_in_discussion_thread(self, message: Message) -> bool:
        if self.is_channel_post(message):
            return True
        if hasattr(message, 'message_thread_id') and message.message_thread_id:
            return True
        return await self._check_reply_chain(message, depth=0)

    async def _check_reply_chain(self, message: Message, depth: int) -> bool:
        if depth >= self.config.max_chain_depth:
            return False
        if not message.reply_to_message:
            return False
        reply = message.reply_to_message
        if self.is_channel_post(reply):
            return True
        if reply.reply_to_message:
            return await self._check_reply_chain(reply, depth + 1)
        if hasattr(reply, 'message_thread_id') and reply.message_thread_id:
            return True
        return False

    async def analyze_chain(self, message: Message, max_depth: int = 10) -> str:
        return await self._analyze_recursive(message, depth=0, max_depth=max_depth)

    async def _analyze_recursive(self, message: Message, depth: int, max_depth: int) -> str:
        if depth >= max_depth:
            return f"{'  ' * depth}⚡ Достигнута максимальная глубина"
        indent = '  ' * depth
        lines = []
        thread_info = ''
        if hasattr(message, 'message_thread_id') and message.message_thread_id:
            thread_info = f" [thread: {message.message_thread_id}]"
        user_info = f" от {message.from_user.id}" if message.from_user else ""
        lines.append(f"{indent}📝 Уровень {depth}: ID {message.message_id}{user_info}{thread_info}")
        if self.is_channel_post(message):
            lines.append(f"{indent}   📢 ПОСТ КАНАЛА")
        if message.reply_to_message:
            reply = message.reply_to_message
            lines.append(f"{indent}   ↪️ Ответ на: {reply.message_id}")
            next_level = await self._analyze_recursive(reply, depth + 1, max_depth)
            lines.append(next_level)
        else:
            lines.append(f"{indent}   🏁 Конец цепочки")
        return '\n'.join(lines)


class WarningManager:
    """Управление предупреждениями с cooldown"""

    def __init__(self, cooldown_seconds: int = 180):
        self.cooldown_seconds = cooldown_seconds
        self.last_warning: Dict[int, datetime] = {}

    def can_warn(self, user_id: int) -> bool:
        if user_id not in self.last_warning:
            return True
        now = datetime.now(timezone.utc)
        elapsed = (now - self.last_warning[user_id]).total_seconds()
        return elapsed >= self.cooldown_seconds

    def record_warning(self, user_id: int) -> None:
        self.last_warning[user_id] = datetime.now(timezone.utc)

    def get_time_until_next_warning(self, user_id: int) -> Optional[int]:
        if user_id not in self.last_warning:
            return None
        now = datetime.now(timezone.utc)
        elapsed = (now - self.last_warning[user_id]).total_seconds()
        remaining = self.cooldown_seconds - elapsed
        return max(0, int(remaining)) if remaining > 0 else None

    async def send_warning(self, bot: Bot, message: Message) -> Optional[int]:
        user_id = message.from_user.id
        if not self.can_warn(user_id):
            remaining = self.get_time_until_next_warning(user_id)
            logger.info(f"Предупреждение не отправлено — cooldown ({remaining}с осталось)")
            return None

        user = message.from_user
        username = f"@{user.username}" if user.username else user.full_name

        warning_text = (
            f"Похоже {username}, вы пишете в общем чате, тогда как Ваш ответ "
            f"должен быть записан как комментарий под постом.\n\n"
            f"Перенесите сообщение в комментарии под соответствующим постом."
        )

        try:
            sent = await bot.send_message(
                chat_id=message.chat.id,
                text=warning_text,
                reply_to_message_id=message.message_id
            )
            self.record_warning(user_id)
            logger.info(f"Отправлено предупреждение пользователю {username}")
            return sent.message_id
        except Exception as e:
            logger.error(f"Ошибка отправки предупреждения: {e}")
            return None


class NotificationService:
    """Уведомления администратору"""

    def __init__(self, bot: Bot, admin_id: int, group_id: int):
        self.bot = bot
        self.admin_id = admin_id
        self.group_id = group_id

    async def send_startup(self) -> None:
        try:
            await self.bot.send_message(
                self.admin_id,
                "🟢 <b>Бот запущен</b>\n\n"
                "Начат мониторинг сообщений вне веток обсуждения канала.\n"
                "Администраторы чата игнорируются.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление о запуске: {e}")

    async def send_shutdown(self) -> None:
        try:
            await self.bot.send_message(
                self.admin_id,
                "🔴 <b>Бот остановлен</b>",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление об остановке: {e}")

    async def notify_off_topic_message(self, message: Message) -> None:
        user = message.from_user
        text = message.text or message.caption or "⚠️ Медиа без текста"
        chat_id_str = str(self.group_id)
        clean_id = chat_id_str[4:] if chat_id_str.startswith('-100') else chat_id_str
        message_link = f"https://t.me/c/{clean_id}/{message.message_id}"

        notification = (
            "⚠️ <b>Сообщение вне ветки обсуждения</b>\n\n"
            f"👤 <b>Пользователь:</b> {html.escape(user.full_name)}"
        )
        if user.username:
            notification += f" (@{user.username})"
        notification += (
            f"\n💬 <b>Текст:</b> {html.escape(text[:100])}"
            f"{'...' if len(text) > 100 else ''}\n"
            f"🔗 <b>Ссылка:</b> <a href='{message_link}'>Сообщение #{message.message_id}</a>"
        )

        try:
            await self.bot.send_message(
                self.admin_id,
                notification,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")


class DiscussionBot:
    """Основной класс бота"""

    def __init__(self, config: BotConfig):
        self.config = config
        self.bot = Bot(token=config.token)
        self.dp = Dispatcher()
        self.analyzer = MessageAnalyzer(config)
        self.notifier = NotificationService(self.bot, config.admin_id, config.group_id)
        self.warning_manager = WarningManager()
        self._admin_cache: Set[int] = set()
        self._admin_cache_time: Optional[datetime] = None
        self._admin_cache_ttl = timedelta(minutes=ADMIN_CACHE_TTL_MINUTES)
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.dp.message.register(
            self._handle_group_message,
            F.chat.id == self.config.group_id
        )
        self.dp.message.register(self._cmd_status, Command('status'))
        self.dp.message.register(self._cmd_test, Command('test'))
        self.dp.message.register(self._cmd_debug, Command('debug_chain'))
        self.dp.message.register(self._cmd_warnings, Command('warnings'))
        self.dp.message.register(
            self._handle_private_message,
            F.chat.type == ChatType.PRIVATE
        )

    @staticmethod
    def _is_service_message(message: Message) -> bool:
        service_fields = [
            'new_chat_members', 'left_chat_member', 'new_chat_title', 'new_chat_photo',
            'delete_chat_photo', 'group_chat_created', 'supergroup_chat_created',
            'channel_chat_created', 'migrate_to_chat_id', 'migrate_from_chat_id',
            'pinned_message', 'invoice', 'successful_payment', 'video_chat_started',
            'video_chat_ended', 'video_chat_scheduled', 'video_chat_participants_invited',
            'web_app_data', 'forum_topic_created', 'forum_topic_edited',
            'forum_topic_closed', 'forum_topic_reopened', 'general_forum_topic_hidden',
            'general_forum_topic_unhidden', 'write_access_allowed'
        ]
        return any(getattr(message, field, None) is not None for field in service_fields)

    async def _get_admin_user_ids_cached(self) -> Set[int]:
        now = datetime.now(timezone.utc)
        if self._admin_cache_time and (now - self._admin_cache_time) < self._admin_cache_ttl:
            return self._admin_cache

        try:
            admins = await self.bot.get_chat_administrators(chat_id=self.config.group_id)
            self._admin_cache = {admin.user.id for admin in admins}
            self._admin_cache_time = now
            logger.debug(f"Обновлён кэш администраторов: {len(self._admin_cache)} пользователей")
            return self._admin_cache
        except Exception as e:
            logger.error(f"Ошибка при получении списка администраторов: {e}")
            return self._admin_cache

    async def _schedule_deletion(self, chat_id: int, message_ids: List[int], delay: int) -> None:
        await asyncio.sleep(delay)
        for msg_id in message_ids:
            try:
                await self.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                logger.debug(f"Сообщение {msg_id} удалено")
            except Exception as e:
                # Игнорируем ошибки: уже удалено, нет прав и т.д.
                logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}")

    async def _handle_group_message(self, message: Message) -> None:
        # Игнорируем администраторов
        if message.from_user:
            admin_ids = await self._get_admin_user_ids_cached()
            if message.from_user.id in admin_ids:
                logger.debug(f"Сообщение от администратора (ID: {message.from_user.id}) — пропущено")
                return

        full_text = (message.text or message.caption or '').strip()
        if full_text.startswith('/'):
            return

        if self._is_service_message(message):
            logger.info(f"Служебное сообщение проигнорировано (ID: {message.message_id})")
            return

        user = message.from_user
        is_post = self.analyzer.is_channel_post(message)
        sender_type = "Пост канала" if is_post else "Пользователь"

        logger.info(
            f"Новое сообщение в группе | От: {user.full_name} (@{user.username}) [ID: {user.id}] - {sender_type} | "
            f"Текст: {message.text or message.caption or '[медиа]'} | ID: {message.message_id}"
        )

        is_in_thread = await self.analyzer.is_in_discussion_thread(message)
        logger.info(f"В ветке обсуждения: {is_in_thread}")

        if not is_in_thread:
            warning_msg_id = await self.warning_manager.send_warning(self.bot, message)
            await self.notifier.notify_off_topic_message(message)
            logger.info("Отправлено уведомление администратору")

            to_delete = [message.message_id]
            if warning_msg_id:
                to_delete.append(warning_msg_id)

            asyncio.create_task(
                self._schedule_deletion(
                    chat_id=message.chat.id,
                    message_ids=to_delete,
                    delay=self.config.auto_delete_delay
                )
            )
        else:
            logger.info("Сообщение проигнорировано (пост канала или комментарий)")

    async def _cmd_status(self, message: Message) -> None:
        if message.from_user.id != self.config.admin_id:
            return
        await message.answer(
            "🟢 <b>Статус бота</b>\n\n"
            "✅ Бот активен\n"
            f"📊 Группа: <code>{self.config.group_id}</code>\n"
            f"📺 Канал: <code>{self.config.channel_id}</code>\n"
            f"👤 Админ: <code>{self.config.admin_id}</code>\n"
            f"⏱ Удаление через: <code>{self.config.auto_delete_delay}с</code>\n"
            "🛡️ Администраторы игнорируются",
            parse_mode='HTML'
        )

    async def _cmd_test(self, message: Message) -> None:
        await message.answer(
            "✅ <b>Бот работает!</b>\n\n"
            "Администраторы игнорируются.\n"
            "Сообщения вне веток удаляются автоматически.",
            parse_mode='HTML'
        )

    async def _cmd_debug(self, message: Message) -> None:
        if message.from_user.id != self.config.admin_id:
            return
        if not message.reply_to_message:
            await message.answer("❌ Ответьте на сообщение для анализа цепочки.")
            return
        chain_info = await self.analyzer.analyze_chain(message.reply_to_message)
        await message.answer(
            f"🔍 <b>Анализ цепочки ответов</b>\n\n"
            f"<pre>{html.escape(chain_info)}</pre>",
            parse_mode='HTML'
        )

    async def _cmd_warnings(self, message: Message) -> None:
        if message.from_user.id != self.config.admin_id:
            return
        if not self.warning_manager.last_warning:
            await message.answer(
                "📊 <b>Статистика предупреждений</b>\n\n"
                "Предупреждений пока не было.",
                parse_mode='HTML'
            )
            return

        lines = ["📊 <b>Статистика предупреждений</b>\n"]
        now = datetime.now(timezone.utc)
        for user_id, timestamp in sorted(
            self.warning_manager.last_warning.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            elapsed = (now - timestamp).total_seconds()
            if elapsed < 60:
                time_str = f"{int(elapsed)}с назад"
            elif elapsed < 3600:
                time_str = f"{int(elapsed // 60)}м назад"
            else:
                time_str = f"{int(elapsed // 3600)}ч назад"

            remaining = self.warning_manager.get_time_until_next_warning(user_id)
            status = f"⏳ {remaining}с" if remaining else "✅ доступно"
            lines.append(f"👤 ID <code>{user_id}</code>: {time_str} [{status}]")

        await message.answer(
            "\n".join(lines) + f"\n\n⏱ Cooldown: 180с | Удаление: {self.config.auto_delete_delay}с",
            parse_mode='HTML'
        )

    async def _handle_private_message(self, message: Message) -> None:
        await message.answer(
            "👋 Привет!\n\n"
            "Я отслеживаю сообщения в группе обсуждения канала.\n"
            "Администраторы игнорируются. Нарушения удаляются автоматически.\n\n"
            "Команды:\n"
            "• /status — статус\n"
            "• /test — проверка\n"
            "• /debug_chain — анализ цепочки (ответом)\n"
            "• /warnings — статистика"
        )

    async def start(self) -> None:
        logger.info("=" * 50)
        logger.info("🚀 Запуск бота мониторинга обсуждений")
        logger.info("🛡️ Администраторы чата игнорируются")
        logger.info(f"⏱ Автоудаление через: {self.config.auto_delete_delay} секунд")
        logger.info("=" * 50)
        logger.info(f"📊 Группа: {self.config.group_id}")
        logger.info(f"📺 Канал: {self.config.channel_id}")
        logger.info(f"👤 Админ: {self.config.admin_id}")
        logger.info("=" * 50)

        await self.notifier.send_startup()
        try:
            await self.dp.start_polling(self.bot)
        except KeyboardInterrupt:
            logger.warning("Получен сигнал остановки")
        except Exception as e:
            logger.critical(f"Критическая ошибка: {e}")
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("🛑 Остановка бота...")
        await self.notifier.send_shutdown()
        await self.bot.session.close()
        logger.info("✅ Бот остановлен")


async def main():
    try:
        config = BotConfig.from_env()
        bot = DiscussionBot(config)
        await bot.start()
    except ValueError as e:
        logger.critical(f"Ошибка конфигурации: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Непредвиденная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())