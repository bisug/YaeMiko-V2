from __future__ import annotations

import logging
import os

import pytest


async def test_chat_migration_runs_in_a_worker(monkeypatch):
    from unittest.mock import MagicMock

    import Mikobot.__main__ as main

    migrated = []

    class Module:
        def __migrate__(self, old, new):
            migrated.append((old, new))

    monkeypatch.setattr(main, "MIGRATEABLE", [Module()])
    message = MagicMock()
    message.migrate_to_chat_id = -100222
    message.migrate_from_chat_id = None
    message.chat.id = -100111

    await main.migrate_chats(None, message)
    assert migrated == [(-100111, -100222)]


def test_env_bool_parser():
    from Mikobot import env_bool

    for val in ("1", "true", "True", "yes", "YES", "on", "ON"):
        os.environ["_TEST_BOOL"] = val
        assert env_bool("_TEST_BOOL") is True

    for val in ("0", "false", "False", "no", "NO", "off", "OFF"):
        os.environ["_TEST_BOOL"] = val
        assert env_bool("_TEST_BOOL") is False

    os.environ.pop("_TEST_BOOL", None)
    assert env_bool("_TEST_BOOL", default=True) is True
    assert env_bool("_TEST_BOOL", default=False) is False

    os.environ["_TEST_BOOL"] = "invalid"
    with pytest.raises(ValueError, match="must be a boolean"):
        env_bool("_TEST_BOOL")
    os.environ.pop("_TEST_BOOL", None)


def test_env_int_parser():
    from Mikobot import env_int

    os.environ["_TEST_INT"] = "42"
    assert env_int("_TEST_INT") == 42

    os.environ.pop("_TEST_INT", None)
    assert env_int("_TEST_INT", default=99) == 99

    with pytest.raises(SystemExit):
        env_int("_TEST_INT")

    os.environ["_TEST_INT"] = "not_a_number"
    with pytest.raises(SystemExit):
        env_int("_TEST_INT")
    os.environ.pop("_TEST_INT", None)


def test_activity_log_enabled_by_default():
    import Mikobot

    assert Mikobot.ACTIVITY_LOG is True


def test_entity_label():
    from types import SimpleNamespace

    from Mikobot.__main__ import _entity_label

    users = {1: SimpleNamespace(username="alice"), 2: SimpleNamespace(first_name="Bob")}
    chats = {100: SimpleNamespace(title="Group")}
    assert _entity_label(1, users) == "1(alice)"
    assert _entity_label(2, users) == "2(Bob)"
    assert _entity_label(100, chats) == "100(Group)"
    assert _entity_label(999, users) == "999"
    assert _entity_label(None, users) == "?"


def test_raw_update_summary_message_and_command():
    from types import SimpleNamespace

    from Mikobot.__main__ import _raw_update_summary

    users = {1: SimpleNamespace(username="alice")}
    chats = {100: SimpleNamespace(title="Group")}
    update = SimpleNamespace(
        message=SimpleNamespace(
            id=55,
            peer_id=SimpleNamespace(channel_id=100),
            from_id=SimpleNamespace(user_id=1),
            message="/start now",
            media=None,
        )
    )
    summary = _raw_update_summary(update, users, chats)
    assert "msg=55" in summary
    assert "chat=100(Group)" in summary
    assert "user=1(alice)" in summary
    assert "command=/start" in summary

    update.message.message = "hello world"
    update.message.media = SimpleNamespace()
    summary = _raw_update_summary(update, users, chats)
    assert "text" in summary
    assert "media" in summary


def test_raw_update_summary_callback_inline_and_unknown():
    from types import SimpleNamespace

    from Mikobot.__main__ import _raw_update_summary

    users = {2: SimpleNamespace(first_name="Bob")}
    chats = {100: SimpleNamespace(title="Group")}

    callback = SimpleNamespace(
        user_id=2, peer=SimpleNamespace(channel_id=100), msg_id=55, data=b"stngs_42"
    )
    summary = _raw_update_summary(callback, users, chats)
    assert "user=2(Bob)" in summary
    assert "chat=100(Group)" in summary
    assert "msg=55" in summary
    assert "data=" in summary

    inline = SimpleNamespace(user_id=2, query="weather")
    summary = _raw_update_summary(inline, users, chats)
    assert "query='weather'" in summary

    # An unknown/empty update must never raise.
    assert _raw_update_summary(SimpleNamespace(), {}, {})


async def test_log_kurigram_activity_emits_info(caplog):
    from types import SimpleNamespace

    from Mikobot.__main__ import log_kurigram_activity

    with caplog.at_level(logging.INFO):
        await log_kurigram_activity(
            None, SimpleNamespace(user_id=1, chat_id=100), {}, {}
        )
    assert any("Activity:" in record.message for record in caplog.records)


def test_redacting_formatter():
    from Mikobot import RedactingFormatter

    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Connecting using bot123456789:AAFDk-0123456789ABCDEF0123456789 to API",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "bot<redacted>" in formatted
    assert "AAFDk-0123456789ABCDEF0123456789" not in formatted


def test_event_loop_creation():
    from Mikobot import _create_event_loop

    loop = _create_event_loop()
    assert loop is not None
    assert not loop.is_closed()
    loop.close()


def test_persistence_store(tmp_path):
    from Mikobot.utils.persistence import open_store

    store_file = tmp_path / "persistence.pickle"
    store = open_store(str(store_file))
    assert hasattr(store, "chat_data")
    assert hasattr(store, "user_data")

    store.chat_data[123] = {"setting": "enabled"}
    store.save()

    reopened = open_store(str(store_file))
    assert reopened.chat_data[123] == {"setting": "enabled"}


async def test_safe_resolve_peer_converts_numeric_strings(monkeypatch):
    from pyrogram import Client

    import Mikobot  # noqa: F401

    resolved = []

    async def fake_orig(self, peer_id):
        resolved.append(peer_id)
        return peer_id

    monkeypatch.setattr(Mikobot, "_orig_resolve_peer", fake_orig)

    client = Client("test", api_id=123, api_hash="abc")

    await Client.resolve_peer(client, "-1001234567890")
    assert resolved[-1] == -1001234567890
    assert isinstance(resolved[-1], int)

    await Client.resolve_peer(client, "987654321")
    assert resolved[-1] == 987654321
    assert isinstance(resolved[-1], int)

    await Client.resolve_peer(client, "@valid_username")
    assert resolved[-1] == "@valid_username"


async def test_job_queue_run_once_name_kwarg():
    import asyncio

    from Mikobot.utils.jobs import JobQueue

    queue = JobQueue()
    called = []

    def callback(x, y):
        called.append((x, y))

    queue.run_once(callback, 0.01, 1, 2, name="test_job")
    await asyncio.sleep(0.05)
    queue.shutdown()
    assert called == [(1, 2)]


async def test_job_queue_reports_task_failure():
    import asyncio

    from Mikobot.utils.jobs import JobQueue

    queue = JobQueue()
    calls = []

    def callback():
        raise RuntimeError("boom")

    queue._report = lambda task: calls.append(task)
    queue.run_once(callback, 0)
    await asyncio.sleep(0.05)
    assert len(calls) == 1
    assert calls[0].exception() is not None
