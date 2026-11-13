import asyncio
import html
import json
import os
import tempfile

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

import Mikobot
from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import dev_plus, sudo_plus
from Mikobot.plugins.helper_funcs.extraction import extract_user
from Mikobot.plugins.log_channel import gloggable
from Mikobot.utils.parser import mention_html

# Resolve relative to this file, not the process working directory, so the bot
# finds the same file regardless of where it was launched from.
ELEVATED_USERS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Mikobot",
    "elevated_users.json",
)

DISASTER_LEVELS = {
    "Dragon": "sudos",
    "Demon": "supports",
    "Wolf": "whitelists",
    "Tiger": "tigers",
}
ELEVATED_USERS_LOCK = asyncio.Lock()


async def check_user_id(user_id: int) -> str | None:
    if not user_id:
        return "That...is a chat! baka ka omae?"
    return None


def update_elevated_users(data):
    directory = os.path.dirname(ELEVATED_USERS_FILE)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=".elevated_users.",
        delete=False,
    ) as outfile:
        temporary = outfile.name
        json.dump(data, outfile, indent=4)
        outfile.flush()
        os.fsync(outfile.fileno())
    try:
        os.replace(temporary, ELEVATED_USERS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_elevated_users(data):
    # The tier names are rebound to lists at the end of Mikobot/__init__.py, so the
    # slice assignment mutates the existing list in place. That matters because other
    # modules bind them with `from Mikobot import DRAGONS`; rebinding would leave
    # those copies stale.
    Mikobot.DRAGONS[:] = sorted(
        set(Mikobot.DEV_USERS)
        | set(Mikobot.CONFIG_SUDOS)
        | {int(user_id) for user_id in data["sudos"]}
    )
    Mikobot.DEMONS[:] = sorted(
        set(Mikobot.CONFIG_DEMONS) | {int(user_id) for user_id in data["supports"]}
    )
    Mikobot.WOLVES[:] = sorted(
        set(Mikobot.CONFIG_WOLVES) | {int(user_id) for user_id in data["whitelists"]}
    )
    Mikobot.TIGERS[:] = sorted(
        set(Mikobot.CONFIG_TIGERS) | {int(user_id) for user_id in data["tigers"]}
    )
    Mikobot.SUPPORT_STAFF[:] = list(
        dict.fromkeys(
            [int(Mikobot.OWNER_ID)]
            + Mikobot.DRAGONS
            + Mikobot.WOLVES
            + Mikobot.DEMONS
            + Mikobot.DEV_USERS
        )
    )


async def add_disaster_level(client, message: Message, level: str) -> str:
    user = message.from_user
    chat = message.chat
    args = message.command[1:] if len(message.command) > 1 else []
    user_id = await extract_user(message, args)
    reply = await check_user_id(user_id)
    if reply:
        await message.reply_text(reply)
        return ""
    my_id = client.me.id if getattr(client, "me", None) else (await client.get_me()).id
    if user_id == int(my_id):
        return ""
    target_name = str(user_id)
    rt = ""

    async with ELEVATED_USERS_LOCK:
        with open(ELEVATED_USERS_FILE) as infile:
            data = json.load(infile)

        target_key = DISASTER_LEVELS[level]
        if user_id in data[target_key]:
            await message.reply_text(f"This user is already a {level} Disaster.")
            return ""

        for disaster_level, disaster_users in DISASTER_LEVELS.items():
            if user_id in data[disaster_users]:
                rt += f"Requested HA to promote this {disaster_level} to {level}."
                data[disaster_users].remove(user_id)

        data[target_key].append(user_id)
        update_elevated_users(data)
        apply_elevated_users(data)

    await message.reply_text(
        rt + f"\nSuccessfully set Disaster level of {target_name} to {level}!"
    )

    log_message = (
        f"#{level.upper()}\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(user_id, target_name)}"
    )

    if chat.type != ChatType.PRIVATE:
        log_message = f"<b>{html.escape(chat.title)}:</b>\n" + log_message

    await message.reply_text(log_message)
    return log_message


@on_message(filters.command("addsudo"), chained=True)
@dev_plus
@gloggable
async def addsudo(client, message: Message) -> str:
    return await add_disaster_level(client, message, "Dragon")


@on_message(filters.command(["addsupport", "adddemon"]), chained=True)
@sudo_plus
@gloggable
async def addsupport(client, message: Message) -> str:
    return await add_disaster_level(client, message, "Demon")


@on_message(filters.command(["addwhitelist", "addwolf"]), chained=True)
@sudo_plus
@gloggable
async def addwhitelist(client, message: Message) -> str:
    return await add_disaster_level(client, message, "Wolf")


@on_message(filters.command("addtiger"), chained=True)
@sudo_plus
@gloggable
async def addtiger(client, message: Message) -> str:
    return await add_disaster_level(client, message, "Tiger")


__mod_name__ = "Devs"
