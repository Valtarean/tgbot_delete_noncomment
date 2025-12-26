import pytest
import asyncio
from types import SimpleNamespace

from analyzer import MessageAnalyzer
from settings import Settings


class DummyMessage(SimpleNamespace):
    pass


@pytest.mark.asyncio
async def test_is_channel_post_by_sender_chat(tmp_path):
    s = Settings(
        BOT_TOKEN="x", ADMIN_ID=1, GROUP_ID=1, CHANNEL_ID=999, _env_file=None
    )
    analyzer = MessageAnalyzer(s)
    msg = DummyMessage(message_id=1, sender_chat=SimpleNamespace(id=999), from_user=None)
    assert analyzer.is_channel_post(msg) is True


@pytest.mark.asyncio
async def test_is_in_thread_via_reply_chain():
    s = Settings(
        BOT_TOKEN="x", ADMIN_ID=1, GROUP_ID=1, CHANNEL_ID=999, _env_file=None
    )
    analyzer = MessageAnalyzer(s)

    # chain: msg3 -> reply to msg2 -> reply to msg1 (which is channel post)
    msg1 = DummyMessage(message_id=1, sender_chat=SimpleNamespace(id=999), from_user=None)
    msg2 = DummyMessage(message_id=2, reply_to_message=msg1, from_user=SimpleNamespace(id=10))
    msg3 = DummyMessage(message_id=3, reply_to_message=msg2, from_user=SimpleNamespace(id=11))

    assert await analyzer.is_in_discussion_thread(msg3) is True


@pytest.mark.asyncio
async def test_not_in_thread():
    s = Settings(
        BOT_TOKEN="x", ADMIN_ID=1, GROUP_ID=1, CHANNEL_ID=999, _env_file=None
    )
    analyzer = MessageAnalyzer(s)
    msg = DummyMessage(message_id=10, from_user=SimpleNamespace(id=20))
    assert await analyzer.is_in_discussion_thread(msg) is False