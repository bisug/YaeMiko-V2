"""Focused regressions for the 2.2.28 native-feature replacements."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import RPCError

ROOT = Path(__file__).resolve().parents[1]


async def test_send_message_does_not_retry_on_rpc_error():
    from Mikobot.plugins.helper_funcs.alternate import send_message

    message = MagicMock()
    message.reply_text = AsyncMock(side_effect=RPCError("no write access"))

    with pytest.raises(RPCError):
        await send_message(message, "hello")

    assert message.reply_text.await_count == 1


def test_gcast_filter_uses_configured_prefixes():
    code = """
from Mikobot.events import registry
from Mikobot.plugins import users
flt = next(r.filters[0] for r in registry.messages if r.handler is users.broadcast_cmd)
print(",".join(sorted(flt.prefixes)))
"""
    env = {
        **os.environ,
        "ENV": "True",
        "ALLOW_EXCL": "True",
        "API_ID": "1",
        "API_HASH": "x",
        "OWNER_ID": "1",
        "TOKEN": "0000000000:CIPLACEHOLDERNOTAREALTOKEN",
    }
    env.pop("DATABASE_URL", None)
    output = subprocess.check_output(
        [sys.executable, "-c", code], cwd=ROOT, env=env, text=True
    )
    prefixes = set(output.strip().split(","))
    assert {"!", "/", "$"} <= prefixes


async def test_get_help_uses_command_argument(monkeypatch):
    import Mikobot.__main__ as main

    module = MagicMock()
    module.__mod_name__ = "Ping"
    module.__help__ = "help body"
    monkeypatch.setattr(main, "HELPABLE", {"ping": module})
    send_help = AsyncMock()
    monkeypatch.setattr(main, "send_help", send_help)

    message = MagicMock()
    message.chat.type = ChatType.PRIVATE
    message.chat.id = 7
    message.text = '/help "ping"'
    message.command = ["help", "ping"]

    await main.get_help(MagicMock(), message)

    send_help.assert_awaited_once()
    assert "help body" in send_help.await_args.args[1]


async def test_topic_delete_accepts_admin_with_privileges():
    from Mikobot.plugins.topics import delete_topic_button

    member = MagicMock(spec=["status", "privileges"])
    member.status = ChatMemberStatus.ADMINISTRATOR
    member.privileges = MagicMock(can_manage_topics=True)
    client = MagicMock()
    client.get_chat_member = AsyncMock(return_value=member)
    client.delete_forum_topic = AsyncMock()

    query = MagicMock()
    query.data = "deltopic_-100_5"
    query.from_user.id = 42
    query.answer = AsyncMock()
    query.message.edit_text = AsyncMock()

    await delete_topic_button(client, query)

    client.delete_forum_topic.assert_awaited_once_with(-100, 5)
    query.answer.assert_awaited_once_with("Deleted.")


async def test_reverse_downloads_the_message_object(monkeypatch):
    from Mikobot.plugins import reverse

    replied = MagicMock()
    replied.photo = [MagicMock()]
    replied.photo[0].file_id = "ignored-file-id"
    message = MagicMock()
    message.text = "/reverse"
    message.reply_to_message = replied
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    status_msg.delete = AsyncMock()
    message.reply_text = AsyncMock(return_value=status_msg)
    client = MagicMock()
    client.download_media = AsyncMock()

    async def write_file(*args, **kwargs):
        Path(kwargs["file_name"]).write_bytes(b"image")

    client.download_media.side_effect = write_file
    response = MagicMock()
    response.json.return_value = {
        "query": "cat",
        "search_url": "https://example.com/search",
    }
    monkeypatch.setattr(reverse.state, "post", AsyncMock(return_value=response))

    await reverse.reverse_image_search(client, message)

    call = client.download_media.await_args
    assert call.args[0] is replied
