import asyncio
from io import BytesIO
from threading import RLock
from time import monotonic

from cachetools import TTLCache
from pyrogram import Client
from pyrogram import filters as fil
from pyrogram.errors import RPCError
from pyrogram.types import Message

import Database.sql.locale_sql as locale_sql
import Database.sql.users_sql as sql
from Database.sql.users_sql import get_all_users
from Mikobot import BOT_ID, DEV_USERS, OWNER_ID
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.consts import ChatID
from Mikobot.utils.errors import FLOOD_WAIT_ERRORS, flood_wait_seconds
from Mikobot.utils.filters import GROUPS

BROADCAST_TARGETS = {"-all", "-group", "-user"}


def parse_broadcast_request(text: str, has_reply: bool = False):
    parts = text.split()
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    if command not in {"/gcast", "!gcast", "$gcast"}:
        return set(), None

    args = parts[1:]
    targets = set(BROADCAST_TARGETS).intersection(args)
    if "-all" in targets:
        targets.update({"-group", "-user"})
    if not targets:
        return set(), None

    content_indexes = {
        index for index, arg in enumerate(args) if arg not in BROADCAST_TARGETS
    }
    content = " ".join(args[index] for index in sorted(content_indexes)).strip()
    if not has_reply and not content:
        return targets, None
    return targets, content or None


@on_message(fil.command("gcast"), chained=True)
async def broadcast_cmd(client: Client, message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id

    if user_id not in [OWNER_ID] + DEV_USERS:
        await message.reply_text(
            "Only the owner and authorized users can use this command."
        )
        return

    targets, content = parse_broadcast_request(
        message.text, has_reply=message.reply_to_message is not None
    )
    if not targets:
        return await message.reply_text(
            "<b>Broadcast commands</b>\n"
            "-user: Broadcast to users.\n"
            "-group: Broadcast to groups.\n"
            "-all: Broadcast to users and groups.\n"
            "Example: <code>/gcast -all message</code> or reply with "
            "<code>/gcast -all</code>"
        )
    if content is None:
        return await message.reply_text("<b>Provide a message or reply to one.</b>")

    tex = await message.reply_text("<code>Starting global broadcast.</code>")

    usersss = 0
    chatttt = 0
    uerror = 0
    cerror = 0
    chats = await asyncio.to_thread(sql.get_all_chats) or []
    users = await asyncio.to_thread(get_all_users)

    async def send_one(target_id):
        if message.reply_to_message:
            await message.reply_to_message.copy(target_id)
        else:
            await client.send_message(target_id, content)

    async def fan_out(target_ids):
        """One send per target; wait out a FloodWait rather than fail.

        Large fan-outs hit the rate limit by design, so honouring the API's delay is what delivers the rest.
        """
        sent = failed = 0
        for target_id in target_ids:
            for attempt in (1, 2):
                try:
                    await send_one(target_id)
                    sent += 1
                    break
                except FLOOD_WAIT_ERRORS as error:
                    if attempt == 2:
                        failed += 1
                        break
                    await asyncio.sleep(flood_wait_seconds(error))
                except Exception:
                    LOGGER.exception("Failed to broadcast to %s", target_id)
                    failed += 1
                    break
            await asyncio.sleep(0.3)
        return sent, failed

    if "-user" in targets:
        usersss, uerror = await fan_out([user.user_id for user in users])
    if "-group" in targets:
        chatttt, cerror = await fan_out([chat.chat_id for chat in chats])

    await tex.edit_text(
        f"<b>Broadcast sent</b>\nUsers: <code>{usersss}</code>\nFailed users: <code>{uerror}</code>\nGroups: <code>{chatttt}</code>\nFailed groups: <code>{cerror}</code>"
    )


async def get_user_id(username: str) -> int | None:
    # Telegram usernames are at least five characters.
    if len(username) <= 5:
        return None

    if username.startswith("@"):
        username = username[1:]

    users = await asyncio.to_thread(sql.get_userid_by_name, username)

    if not users:
        return None

    elif len(users) == 1:
        return users[0].user_id

    else:
        for user_obj in users:
            if (user_obj.username or "").lower() == username.lower():
                return user_obj.user_id

    return None


USER_DB_CACHE = TTLCache(maxsize=10_000, ttl=300, timer=monotonic)
BOT_STATUS_CACHE = TTLCache(maxsize=10_000, ttl=600, timer=monotonic)
USER_DB_LOCK = RLock()


def _user_db_is_fresh(user_id, username, chat_id, chat_name):
    key = (user_id, chat_id)
    with USER_DB_LOCK:
        return USER_DB_CACHE.get(key) == (username, chat_name)


def _mark_user_db_fresh(user_id, username, chat_id, chat_name):
    with USER_DB_LOCK:
        USER_DB_CACHE[(user_id, chat_id)] = (username, chat_name)


async def _async_update_user(user_id, username, chat_id, chat_title):
    try:
        await asyncio.to_thread(sql.update_user, user_id, username, chat_id, chat_title)
    except Exception:
        LOGGER.exception("Failed to update user in database")


@on_message(GROUPS, chained=True)
async def log_user(client: Client, message: Message):
    chat = message.chat
    msg = message

    if msg.from_user and not _user_db_is_fresh(
        msg.from_user.id, msg.from_user.username, chat.id, chat.title
    ):
        _mark_user_db_fresh(
            msg.from_user.id, msg.from_user.username, chat.id, chat.title
        )
        asyncio.create_task(
            _async_update_user(
                msg.from_user.id,
                msg.from_user.username,
                chat.id,
                chat.title,
            )
        )

    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and not _user_db_is_fresh(
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )
    ):
        _mark_user_db_fresh(
            msg.reply_to_message.from_user.id,
            msg.reply_to_message.from_user.username,
            chat.id,
            chat.title,
        )
        asyncio.create_task(
            _async_update_user(
                msg.reply_to_message.from_user.id,
                msg.reply_to_message.from_user.username,
                chat.id,
                chat.title,
            )
        )


@check_admin(only_dev=True)
@on_message(fil.command("groups"), chained=True)
async def chats(client: Client, message: Message):
    all_chats = await asyncio.to_thread(sql.get_all_chats) or []
    chatfile = "List of chats.\n0. Chat Name | Chat ID | Members Count\n"
    P = 1
    for chat in all_chats:
        try:
            await client.get_chat(chat.chat_id)
            chat_members = await client.get_chat_members_count(chat.chat_id)
            chatfile += "{}. {} | {} | {}\n".format(
                P,
                chat.chat_name,
                chat.chat_id,
                chat_members,
            )
            P = P + 1
        except RPCError:
            # Skip unreachable chats (kicked, renamed, bot removed) so one bad
            # entry does not spoil the export.
            LOGGER.debug("Skipped unreadable chat %s", chat.chat_id)

    with BytesIO(str.encode(chatfile)) as output:
        output.name = "groups_list.txt"
        await message.reply_document(
            document=output,
            caption="Groups in the database.",
        )


@on_message(GROUPS, chained=True)
async def chat_checker(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id in BOT_STATUS_CACHE:
        return
    try:
        await client.get_chat_member(chat_id, client.me.id)
        BOT_STATUS_CACHE[chat_id] = True
    except RPCError:
        BOT_STATUS_CACHE[chat_id] = True


def __user_info__(user_id):
    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        return """Groups Count: ???"""
    if user_id == BOT_ID:
        return """Groups Count: ???"""
    num_chats = sql.get_user_num_chats(user_id)
    return f"""Groups Count: {num_chats}"""


def __stats__():
    return f"• {sql.num_users()} users, across {sql.num_chats()} chats"


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)
    # The per-chat language lives in its own module with no plugin of its own.
    locale_sql.migrate_chat(old_chat_id, new_chat_id)


__mod_name__ = "Users"
