from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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


def test_lazy_imports_configuration():
    if hasattr(sys, "set_lazy_imports"):
        import Mikobot  # noqa: F401

        assert sys.get_lazy_imports() in ("all", True)


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
