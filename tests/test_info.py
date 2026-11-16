from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Chat, Message, User

from Mikobot.plugins import info

USER_ID = 7804972365


def _user_chat(bio):
    user = MagicMock()
    user.id = USER_ID
    user.type = ChatType.PRIVATE
    user.first_name = "TestUser"
    user.last_name = None
    user.username = "testuser"
    user.bio = bio
    user.photo = None
    return user


def _info_message(chat, command):
    message = MagicMock(spec=Message)
    message.chat = chat
    message.command = command
    message.from_user = User(
        id=USER_ID, is_bot=False, first_name="TestUser", username="testuser"
    )
    message.reply_to_message = None
    message.reply_text = AsyncMock()
    return message


async def test_info_in_private_chat_does_not_call_get_chat_member():
    client = AsyncMock()
    client.get_chat.return_value = _user_chat("Hello")

    # In private chat, get_chat_member would raise ValueError if called
    client.get_chat_member.side_effect = ValueError(
        f'The chat_id "{USER_ID}" belongs to a user'
    )

    message = _info_message(Chat(id=USER_ID, type=ChatType.PRIVATE), ["info"])

    with patch("Mikobot.plugins.info.is_approved", return_value=False):
        await info.info(client, message)

    client.get_chat_member.assert_not_called()
    assert message.reply_text.called


async def test_info_in_group_calls_get_chat_member():
    client = AsyncMock()
    client.get_chat.return_value = _user_chat(None)

    member = MagicMock(status=ChatMemberStatus.ADMINISTRATOR, custom_title="Boss")
    client.get_chat_member.return_value = member

    message = _info_message(
        Chat(id=-1001234567890, type=ChatType.SUPERGROUP),
        ["info", str(USER_ID)],
    )

    with patch("Mikobot.plugins.info.is_approved", return_value=True):
        await info.info(client, message)

    client.get_chat_member.assert_called_once_with(-1001234567890, USER_ID)
    sent_text = message.reply_text.call_args[0][0]
    assert "<b>Admin Title:</b> Boss" in sent_text
    assert "<b>Approved:</b> This user is approved in this chat." in sent_text
