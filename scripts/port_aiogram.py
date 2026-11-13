"""One-shot mechanical pass for the aiogram to kurigram port.

Renames the calls that map one to one and swaps the imports. Everything that
needs a decision (handler signatures, registration, command arguments) is
left alone for the plugin ports to finish by hand.

Usage: python scripts/port_aiogram.py [paths...]
"""

import re
import sys
from pathlib import Path

# Imports that map one to one.
IMPORT_MAP = {
    "from aiogram.types import": "from pyrogram.types import",
    "from aiogram.enums import": "from pyrogram.enums import",
    "from aiogram.exceptions import TelegramAPIError": (
        "from pyrogram.errors import RPCError"
    ),
    "from aiogram.exceptions import (": "from pyrogram.errors import (",
    "from aiogram.exceptions import TelegramForbiddenError": (
        "from pyrogram.errors import RPCError"
    ),
    "from aiogram.exceptions import TelegramRetryAfter": (
        "from pyrogram.errors import FloodWait"
    ),
    "from aiogram.exceptions import TelegramNetworkError": (
        "from pyrogram.errors import RPCError"
    ),
    "from aiogram.exceptions import TelegramServerError": (
        "from pyrogram.errors import RPCError"
    ),
    "from aiogram.exceptions import TelegramBadRequest": (
        "from pyrogram.errors import RPCError"
    ),
    "from aiogram.filters import Comma": "from pyrogram import filters",
}

# Calls on a message. kurigram has no answer(), it has reply_text() and one
# reply_* per media.
MESSAGE_CALLS = {
    ".answer(": ".reply_text(",
    ".answer_photo(": ".reply_photo(",
    ".answer_document(": ".reply_document(",
    ".answer_sticker(": ".reply_sticker(",
    ".answer_video(": ".reply_video(",
    ".answer_voice(": ".reply_voice(",
    ".answer_audio(": ".reply_audio(",
    ".answer_video_note(": ".reply_video_note(",
    ".answer_media_group(": ".reply_media_group(",
    ".reply(": ".reply_text(",
}

# Calls on the bot object.
CLIENT_CALLS = {
    ".get_chat_member_count(": ".get_chat_members_count(",
    ".set_chat_administrator_custom_title(": ".set_administrator_title(",
    ".create_chat_invite_link(": ".create_invite_link(",
    ".edit_chat_invite_link(": ".edit_invite_link(",
    ".revoke_chat_invite_link(": ".revoke_invite_link(",
    ".delete_message(": ".delete_messages(",
    ".download(": ".download_media(",
    ".answer_callback_query(": ".answer_callback_query(",
}

# Error names that changed.
NAME_MAP = {
    "TelegramAPIError": "RPCError",
    "TelegramForbiddenError": "RPCError",
    "TelegramServerError": "RPCError",
    "TelegramNetworkError": "RPCError",
    "TelegramBadRequest": "RPCError",
    "TelegramRetryAfter": "FloodWait",
    "TelegramMigrateToChat": "RPCError",
}


def port(text: str) -> str:
    for old, new in IMPORT_MAP.items():
        text = text.replace(old, new)

    for old, new in NAME_MAP.items():
        text = re.sub(rf"\b{old}\b", new, text)

    # bot. -> client. , but only where the object is the aiogram bot.
    text = re.sub(r"\bbot\.", "client.", text)

    # The reply calls belong to a message. A callback query has no reply, it
    # answers, and kurigram keeps that name.
    for old, new in MESSAGE_CALLS.items():
        text = re.sub(
            rf"\b(message|msg|m|sent|guu|response)\b{re.escape(old)}",
            rf"\1{new}",
            text,
        )

    for old, new in CLIENT_CALLS.items():
        text = re.sub(rf"\b(bot|client)\b{re.escape(old)}", rf"\1{new}", text)

    return text


def main() -> None:
    targets = sys.argv[1:] or ["Mikobot", "Infamous", "Database"]
    changed = []
    for target in targets:
        for path in Path(target).rglob("*.py"):
            source = path.read_text()
            ported = port(source)
            if ported != source:
                path.write_text(ported)
                changed.append(str(path))
    for name in changed:
        print(name)


if __name__ == "__main__":
    main()
