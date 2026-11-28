"""Regressions from the final whole-change review."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pyrogram.enums import ChatType

from Mikobot.plugins import feds, users


async def test_fed_broadcast_does_not_propagate_source_thread_id(monkeypatch):
    sql = MagicMock()
    sql.get_fed_id.return_value = "fed"
    sql.get_fed_info.return_value = {"fname": "F"}
    sql.all_fed_chats.return_value = [123, 456]
    monkeypatch.setattr(feds, "sql", sql)
    monkeypatch.setattr(feds, "is_user_fed_owner", lambda *a: True)
    monkeypatch.setattr(feds, "markdown_parser", lambda text, offset=0: text)
    monkeypatch.setattr(feds, "mention_markdown", lambda *a: "mention")
    notify = AsyncMock()
    monkeypatch.setattr(feds, "_notify", notify)

    message = MagicMock()
    message.chat.type = ChatType.GROUP
    message.chat.id = -100
    message.from_user.id = 1
    message.from_user.first_name = "A"
    message.from_user.last_name = None
    message.text = "/fbroadcast hello"
    message.command = ["fbroadcast", "hello"]
    message.message_thread_id = 99
    message.reply_text = AsyncMock()

    await feds.fed_broadcast(MagicMock(), message)

    assert notify.await_count == 2
    assert all("message_thread_id" not in c.kwargs for c in notify.await_args_list)


def test_broadcast_parser_accepts_configured_prefix(monkeypatch):
    monkeypatch.setattr(users, "CMD_STARTERS", ("/", "!", ".", "-", "$", "*", "+"))
    for prefix in ("/", "!", ".", "-", "$", "*", "+"):
        targets, content = users.parse_broadcast_request(f"{prefix}gcast -all hi")
        assert targets == {"-all", "-group", "-user"}
        assert content == "hi"
