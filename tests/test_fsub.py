from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram import StopPropagation
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, Message, User

from Mikobot.plugins import fsub


def _fsub_message():
    message = MagicMock(spec=Message)
    message.chat = Chat(id=-1001234567890, type=ChatType.SUPERGROUP)
    message.from_user = User(id=987654321, is_bot=False, first_name="NormalUser")
    message.reply_text = AsyncMock()
    return message


async def test_fsub_disabled_chat_allows_continuation():
    client = AsyncMock()
    message = _fsub_message()

    with patch("Database.sql.fsub_sql.fs_settings", return_value=None):
        # Should return None and not raise StopPropagation
        await fsub.force_subscribe_new_message(client, message)

    client.restrict_chat_member.assert_not_called()


async def test_fsub_unsubscribed_user_is_muted_and_stops_propagation():
    client = AsyncMock()
    message = _fsub_message()

    sender_member = MagicMock()
    sender_member.status = ChatMemberStatus.MEMBER

    bot_member = MagicMock()
    bot_member.status = ChatMemberStatus.ADMINISTRATOR
    bot_member.privileges = MagicMock()
    bot_member.privileges.can_restrict_members = True

    client.get_chat_member.side_effect = [sender_member, bot_member]

    with (
        patch(
            "Database.sql.fsub_sql.fs_settings", return_value={"channel": "TestChannel"}
        ),
        patch("Mikobot.plugins.fsub.participant_check", return_value=False),
        patch("Mikobot.plugins.fsub.has_restrict_rights", return_value=True),
        pytest.raises(StopPropagation),
    ):
        await fsub.force_subscribe_new_message(client, message)

    assert message.reply_text.called
    client.restrict_chat_member.assert_called_once()
