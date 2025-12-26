import pytest
import asyncio
import os
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

from warning_manager import WarningManager
from db import init_db, get_last_warning, set_last_warning

DB_TEST = "data/test_bot.sqlite3"


@pytest.mark.asyncio
async def setup_db(tmp_path):
    dbp = tmp_path / "test_bot.sqlite3"
    await init_db(str(dbp))
    return str(dbp)


@pytest.mark.asyncio
async def test_cooldown_and_record(tmp_path):
    dbp = str(tmp_path / "wtest.sqlite3")
    await init_db(dbp)
    wm = WarningManager(cooldown_seconds=2, db_path=dbp)

    user_id = 123
    # initially can warn
    assert await wm.can_warn(user_id) is True

    # record warning
    await wm.record_warning(user_id)
    assert await get_last_warning(dbp, user_id) is not None

    # immediately cannot warn
    assert await wm.can_warn(user_id) is False

    # wait for cooldown
    await asyncio.sleep(2.1)
    assert await wm.can_warn(user_id) is True


@pytest.mark.asyncio
async def test_send_warning_no_from_user(monkeypatch, tmp_path):
    dbp = str(tmp_path / "wtest2.sqlite3")
    await init_db(dbp)
    wm = WarningManager(cooldown_seconds=1, db_path=dbp)

    class DummyBot:
        async def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode=None):
            return SimpleNamespace(message_id=999)

    dummy = DummyBot()
    msg = SimpleNamespace(from_user=None, chat=SimpleNamespace(id=1), message_id=1)
    res = await wm.send_warning(dummy, msg)
    assert res is None