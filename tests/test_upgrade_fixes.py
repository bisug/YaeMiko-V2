"""Focused regressions for the approved bug fixes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import FloodWait

from Mikobot.plugins import admin as admin_plugin
from Mikobot.plugins import quotely as quotely_plugin
from Mikobot.plugins import settings_export, unbanall
from Mikobot.plugins import users as users_plugin


async def _members(*members):
    for member in members:
        yield member


async def test_unbanall_retries_after_flood_wait(monkeypatch):
    monkeypatch.setattr(unbanall, "is_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(unbanall, "has_restrict_rights", lambda member: True)
    monkeypatch.setattr(unbanall, "sleep", AsyncMock())

    member = MagicMock()
    member.user.id = 7
    client = MagicMock()
    client.get_chat_member = AsyncMock(return_value=MagicMock())
    client.get_me = AsyncMock(return_value=MagicMock(id=1))
    client.get_chat_members = lambda *a, **k: _members(member)
    client.unban_chat_member = AsyncMock(side_effect=[FloodWait(1), None])

    message = MagicMock()
    message.chat.type = ChatType.GROUP
    message.chat.id = -100
    message.command = ["unbanall"]
    message.from_user.id = 9
    message.reply_text = AsyncMock(return_value=MagicMock(edit=AsyncMock()))

    await unbanall.bulk_moderation(client, message)

    assert client.unban_chat_member.await_count == 2
    assert "1 users" in message.reply_text.return_value.edit.await_args.args[0]


async def test_reset_cancel_parses_chat_id():
    query = MagicMock()
    query.data = "settings_reset_cancel_-100123"
    query.message.edit_text = AsyncMock()
    query.answer = AsyncMock()

    await settings_export.reset_button(MagicMock(), query)

    query.message.edit_text.assert_awaited_once_with("Reset cancelled.")


async def test_adminlist_keeps_both_bot_admins():
    client = MagicMock()
    bots = []
    for user_id in (11, 12):
        member = MagicMock()
        member.user.id = user_id
        member.user.is_bot = True
        member.user.first_name = f"Bot{user_id}"
        member.user.last_name = None
        member.status = ChatMemberStatus.ADMINISTRATOR
        member.custom_title = None
        bots.append(member)
    client.get_chat_members = lambda *a, **k: _members(*bots)

    message = MagicMock()
    message.chat.type = ChatType.GROUP
    message.chat.id = -100
    message.chat.title = "Test"
    status = MagicMock()
    status.edit_text = AsyncMock()
    message.reply_text = AsyncMock(return_value=status)

    await admin_plugin.adminlist(client, message)

    text = status.edit_text.await_args.args[0]
    bots_section = text.split("<b>Bots:</b>")[1]
    assert "Bot11" in bots_section and "Bot12" in bots_section


async def test_get_user_id_accepts_five_character_username(monkeypatch):
    row = MagicMock()
    row.user_id = 42
    row.username = "abcde"
    monkeypatch.setattr(
        users_plugin.sql, "get_userid_by_name", lambda username: [row]
    )

    assert await users_plugin.get_user_id("abcde") == 42


async def test_quote_fallback_keeps_messages(monkeypatch):
    searcher = AsyncMock(
        side_effect=[
            ValueError("bad api"),
            {"ok": False, "error": {"message": "stop"}},
        ]
    )
    monkeypatch.setattr(quotely_plugin, "async_searcher", searcher)
    quotly = quotely_plugin.Quotly()
    monkeypatch.setattr(
        quotly, "_format_quote", AsyncMock(side_effect=lambda message, **k: str(message))
    )

    with pytest.raises(RuntimeError):
        await quotly.create_quotly(
            ["message"], url="https://other.example", reply="r", sender="s", bg="#fff"
        )

    second = searcher.await_args_list[1].kwargs["json"]
    assert second["messages"] == ["message"]
