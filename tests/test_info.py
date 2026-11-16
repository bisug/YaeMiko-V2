from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, Message, User

from Mikobot.plugins import info


@pytest.mark.asyncio
async def test_info_in_private_chat_does_not_call_get_chat_member():
    client = AsyncMock()
    user_chat_obj = MagicMock()
    user_chat_obj.id = 7804972365
    user_chat_obj.type = ChatType.PRIVATE
    user_chat_obj.first_name = "TestUser"
    user_chat_obj.last_name = None
    user_chat_obj.username = "testuser"
    user_chat_obj.bio = "Hello"
    user_chat_obj.photo = None

    client.get_chat.return_value = user_chat_obj

    # In private chat, get_chat_member would raise ValueError if called
    client.get_chat_member.side_effect = ValueError(
        'The chat_id "7804972365" belongs to a user'
    )

    message = MagicMock(spec=Message)
    message.chat = Chat(id=7804972365, type=ChatType.PRIVATE)
    message.command = ["info"]
    message.from_user = User(
        id=7804972365, is_bot=False, first_name="TestUser", username="testuser"
    )
    message.reply_to_message = None

    reply_mock = AsyncMock()
    message.reply_text = AsyncMock(return_value=reply_mock)

    with patch("Mikobot.plugins.info.is_approved", return_value=False):
        await info.info(client, message)

    # In private chat, get_chat_member must NOT have been called
    client.get_chat_member.assert_not_called()
    assert message.reply_text.called


@pytest.mark.asyncio
async def test_info_in_group_calls_get_chat_member():
    client = AsyncMock()
    user_chat_obj = MagicMock()
    user_chat_obj.id = 7804972365
    user_chat_obj.type = ChatType.PRIVATE
    user_chat_obj.first_name = "TestUser"
    user_chat_obj.last_name = None
    user_chat_obj.username = "testuser"
    user_chat_obj.bio = None
    user_chat_obj.photo = None

    client.get_chat.return_value = user_chat_obj

    member_mock = MagicMock()
    member_mock.status = ChatMemberStatus.ADMINISTRATOR
    member_mock.custom_title = "Boss"
    client.get_chat_member.return_value = member_mock

    message = MagicMock(spec=Message)
    message.chat = Chat(id=-1001234567890, type=ChatType.SUPERGROUP)
    message.command = ["info", "7804972365"]
    message.from_user = User(id=7804972365, is_bot=False, first_name="TestUser")
    message.reply_to_message = None

    reply_mock = AsyncMock()
    message.reply_text = AsyncMock(return_value=reply_mock)

    with patch("Mikobot.plugins.info.is_approved", return_value=True):
        await info.info(client, message)

    client.get_chat_member.assert_called_once_with(-1001234567890, 7804972365)
    sent_text = message.reply_text.call_args[0][0]
    assert "<b>Admin Title:</b> Boss" in sent_text
    assert "<b>Approved:</b> This user is approved in this chat." in sent_text
