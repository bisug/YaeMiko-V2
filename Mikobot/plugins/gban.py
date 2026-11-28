import asyncio
import html
import time
from datetime import datetime, timezone
from io import BytesIO

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import Message

import Database.sql.global_bans_sql as sql
from Database.sql.userinfo_sql import get_user_info
from Database.sql.users_sql import get_user_com_chats
from Mikobot import (
    BOT_ID,
    DEV_USERS,
    DRAGONS,
    EVENT_LOGS,
    OWNER_ID,
    STRICT_GBAN,
    SUPPORT_CHAT,
)
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.helper_funcs.chat_status import (
    check_admin,
    granted,
    is_user_admin,
    support_plus,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user, extract_user_and_text
from Mikobot.plugins.helper_funcs.misc import send_to_list
from Mikobot.utils.consts import ChatID
from Mikobot.utils.errors import FLOOD_WAIT_ERRORS, flood_wait_seconds
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html

# Kurigram names errors by ID. The old aiogram-style phrases never appear in
# a 2.2.27 RPCError, so every expected failure was logged as unexpected.
GBAN_ERRORS = {
    "USER_ADMIN_INVALID",
    "CHAT_INVALID",
    "CHAT_ADMIN_REQUIRED",
    "RIGHT_FORBIDDEN",
    "USER_NOT_PARTICIPANT",
    "PEER_ID_INVALID",
    "CHANNEL_PRIVATE",
    "USER_CREATOR",
    "ADMIN_RANK_INVALID",
}

UNGBAN_ERRORS = {
    "USER_ADMIN_INVALID",
    "CHAT_INVALID",
    "CHAT_ADMIN_REQUIRED",
    "RIGHT_FORBIDDEN",
    "USER_NOT_PARTICIPANT",
    "CHANNEL_INVALID",
    "CHANNEL_PRIVATE",
    "PEER_ID_INVALID",
    "USER_INVALID",
    "USER_CREATOR",
}


def _matches_gban_error(excp: Exception, error_set: set[str]) -> bool:
    ident = getattr(excp, "ID", None)
    if ident in error_set:
        return True
    # Unknown errors carry no ID but still print their error name in str().
    err_str = str(excp).lower()
    return any(name.lower() in err_str for name in error_set)


async def check_and_ban(client, message: Message, user_id, should_message=True):
    if sql.is_user_gbanned(user_id):
        await client.ban_chat_member(message.chat.id, user_id)
        if should_message:
            text = (
                f"<b>Alert</b>: This user is globally banned.\n"
                f"<code>Banned from this chat</code>.\n"
                f"<b>Appeal chat</b>: @{SUPPORT_CHAT}\n"
                f"<b>User ID</b>: <code>{user_id}</code>"
            )
            user = await asyncio.to_thread(sql.get_gbanned_user, user_id)
            if user.reason:
                text += f"\n<b>Ban Reason:</b> <code>{html.escape(user.reason)}</code>"
            await message.reply_text(text, parse_mode=ParseMode.HTML)


@on_message(GROUPS, chained=True)
async def enforce_gban(client, message: Message):
    if not STRICT_GBAN:
        return
    chat = message.chat
    if not sql.does_chat_gban(chat.id):
        return

    user = message.from_user
    new_members = message.new_chat_members or []
    reply_user = (
        message.reply_to_message.from_user if message.reply_to_message else None
    )

    # Fast path: check in-memory GBANNED_LIST before making any Telegram API calls.
    has_gbanned = (
        (user and sql.is_user_gbanned(user.id))
        or any(sql.is_user_gbanned(mem.id) for mem in new_members)
        or (reply_user and sql.is_user_gbanned(reply_user.id))
    )
    if not has_gbanned:
        return

    try:
        get_member = await client.get_chat_member(chat.id, client.me.id)
    except RPCError:
        return
    # kurigram keeps the administrator rights in member.privileges.
    if get_member.status != ChatMemberStatus.ADMINISTRATOR or not granted(
        get_member, "can_restrict_members"
    ):
        return

    if user and sql.is_user_gbanned(user.id):
        if not await is_user_admin(chat, user.id):
            await check_and_ban(client, message, user.id)
            return

    for mem in new_members:
        if sql.is_user_gbanned(mem.id):
            await check_and_ban(client, message, mem.id)

    if reply_user and sql.is_user_gbanned(reply_user.id):
        if not await is_user_admin(chat, reply_user.id):
            await check_and_ban(client, message, reply_user.id, should_message=False)


@support_plus
@on_message(filters.command("gban"), chained=True)
async def gban(client, message: Message):
    args = message.command[1:] if message.command else []
    user = message.from_user
    chat = message.chat
    log_message = ""

    user_id, reason = await extract_user_and_text(message, args)

    if not user_id:
        await message.reply_text(
            "Mention a user or provide a valid ID.",
        )
        return

    if int(user_id) in DEV_USERS:
        await message.reply_text(
            "That user is part of the Association.\nThe bot cannot act against its own.",
        )
        return

    if int(user_id) in DRAGONS:
        await message.reply_text(
            "That user is a dragon and cannot be banned.",
        )
        return

    if user_id == client.me.id:
        await message.reply_text("The bot cannot ban itself.")
        return

    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        await message.reply_text(
            "The bot cannot act against Telegram's native accounts."
        )
        return

    user_info = get_user_info(user_id) or {}
    user_name = user_info.get("name") or str(user_id)
    user_username = user_info.get("username") or None
    user_target = mention_html(user_id, user_name)

    if sql.is_user_gbanned(user_id):
        if not reason:
            await message.reply_text(
                "This user is already globally banned. Provide a reason to change it.",
            )
            return

        old_reason = sql.update_gban_reason(user_id, user_username or user_name, reason)
        if old_reason:
            await message.reply_text(
                "This user is already globally banned for this reason:\n"
                "<code>{}</code>\n"
                "The reason has been updated.".format(
                    html.escape(old_reason),
                ),
                parse_mode=ParseMode.HTML,
            )

        else:
            await message.reply_text(
                "This user is already globally banned. The reason has been set.",
            )

        return

    await message.reply_text("Banning the user.")

    datetime_fmt = "%Y-%m-%dT%H:%M"
    current_time = datetime.now(timezone.utc).strftime(datetime_fmt)

    if chat.type != ChatType.PRIVATE:
        chat_origin = "<b>{} ({})</b>\n".format(html.escape(chat.title), chat.id)
    else:
        chat_origin = "<b>{}</b>\n".format(chat.id)

    log_message = (
        f"#GBANNED\n"
        f"<b>Originated from:</b> <code>{chat_origin}</code>\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>Banned User:</b> {user_target}\n"
        f"<b>Banned User ID:</b> <code>{user_id}</code>\n"
        f"<b>Event Stamp:</b> <code>{current_time}</code>"
    )

    if reason:
        if chat.type == ChatType.SUPERGROUP and chat.username:
            log_message += f'\n<b>Reason:</b> <a href="https://telegram.me/{chat.username}/{message.id}">{html.escape(reason)}</a>'
        else:
            log_message += f"\n<b>Reason:</b> <code>{html.escape(reason)}</code>"

    if EVENT_LOGS:
        try:
            log = await client.send_message(
                EVENT_LOGS, log_message, parse_mode=ParseMode.HTML
            )
        except RPCError:
            log = await client.send_message(
                EVENT_LOGS,
                log_message
                + "\n\nFormatting has been disabled due to an unexpected error.",
            )

    else:
        await send_to_list(client, DRAGONS, log_message, html=True)

    await asyncio.to_thread(sql.gban_user, user_id, user_username or user_name, reason)

    chats = await asyncio.to_thread(get_user_com_chats, user_id)
    gbanned_chats = 0

    for chat in chats:
        chat_id = int(chat)

        if not await asyncio.to_thread(sql.does_chat_gban, chat_id):
            continue

        for attempt in (1, 2):
            try:
                await client.ban_chat_member(chat_id, user_id)
                gbanned_chats += 1
                break
            except FLOOD_WAIT_ERRORS as excp:
                if attempt == 2:
                    LOGGER.warning("Gave up banning in %s after FloodWait", chat_id)
                    break
                await asyncio.sleep(flood_wait_seconds(excp))
            except RPCError as excp:
                if _matches_gban_error(excp, GBAN_ERRORS):
                    break
                await message.reply_text(f"Could not globally ban: {excp.message}")
                if EVENT_LOGS:
                    await client.send_message(
                        EVENT_LOGS,
                        f"Could not globally ban: {excp.message}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await send_to_list(
                        client,
                        DRAGONS,
                        f"Could not globally ban: {excp.message}",
                    )
                await asyncio.to_thread(sql.ungban_user, user_id)
                return

    if EVENT_LOGS:
        await log.edit_text(
            log_message + f"\n<b>Chats affected:</b> <code>{gbanned_chats}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await send_to_list(
            client,
            DRAGONS,
            f"Global ban complete (user banned in <code>{gbanned_chats}</code> chats).",
            html=True,
        )

    await message.reply_text("Global ban complete.", parse_mode=ParseMode.HTML)

    try:
        await client.send_message(
            user_id,
            "#EVENT\n"
            "You have been marked as malicious and banned from all groups this bot manages."
            f"\n<b>Reason:</b> <code>{html.escape(reason or 'No reason provided')}</code>"
            f"\n<b>Appeal Chat:</b> @{SUPPORT_CHAT}",
            parse_mode=ParseMode.HTML,
        )
    except RPCError:
        # The user may have blocked the bot, which is exactly why they are being
        # banned. The global ban is already recorded either way.
        LOGGER.debug("Could not DM the gban notice to %s", user_id, exc_info=True)


@support_plus
@on_message(filters.command("ungban"), chained=True)
async def ungban(client, message: Message):
    args = message.command[1:] if message.command else []
    user = message.from_user
    chat = message.chat
    log_message = ""

    user_id = await extract_user(message, args)

    if not user_id:
        await message.reply_text(
            "Mention a user or provide a valid ID.",
        )
        return

    user_info = get_user_info(user_id) or {}
    user_name = user_info.get("name") or str(user_id)
    user_target = mention_html(user_id, user_name)

    if not sql.is_user_gbanned(user_id):
        await message.reply_text("This user is not globally banned.")
        return

    await message.reply_text(f"Giving {user_name} a second chance globally.")

    start_time = time.time()
    datetime_fmt = "%Y-%m-%dT%H:%M"
    current_time = datetime.now(timezone.utc).strftime(datetime_fmt)

    if chat.type != ChatType.PRIVATE:
        chat_origin = f"<b>{html.escape(chat.title)} ({chat.id})</b>\n"
    else:
        chat_origin = f"<b>{chat.id}</b>\n"

    log_message = (
        f"#UNGBANNED\n"
        f"<b>Originated from:</b> <code>{chat_origin}</code>\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>Unbanned User:</b> {user_target}\n"
        f"<b>Unbanned User ID:</b> <code>{user_id}</code>\n"
        f"<b>Event Stamp:</b> <code>{current_time}</code>"
    )

    if EVENT_LOGS:
        try:
            log = await client.send_message(
                EVENT_LOGS, log_message, parse_mode=ParseMode.HTML
            )
        except RPCError:
            log = await client.send_message(
                EVENT_LOGS,
                log_message
                + "\n\nFormatting has been disabled due to an unexpected error.",
            )
    else:
        await send_to_list(client, DRAGONS, log_message, html=True)

    chats = get_user_com_chats(user_id)
    ungbanned_chats = 0

    for chat in chats:
        chat_id = int(chat)

        if not sql.does_chat_gban(chat_id):
            continue

        try:
            member = await client.get_chat_member(chat_id, user_id)
            if member.status == ChatMemberStatus.BANNED:
                await client.unban_chat_member(chat_id, user_id)
                ungbanned_chats += 1

        except RPCError as excp:
            if _matches_gban_error(excp, UNGBAN_ERRORS):
                pass
            else:
                await message.reply_text(
                    f"Could not remove the global ban: {excp.message}"
                )
                if EVENT_LOGS:
                    await client.send_message(
                        EVENT_LOGS,
                        f"Could not remove the global ban: {excp.message}",
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await client.send_message(
                        OWNER_ID,
                        f"Could not remove the global ban: {excp.message}",
                    )
                return

    sql.ungban_user(user_id)

    if EVENT_LOGS:
        await log.edit_text(
            log_message + f"\n<b>Chats affected:</b> {ungbanned_chats}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await send_to_list(client, DRAGONS, "Global ban removed.")

    end_time = time.time()
    ungban_time = round((end_time - start_time), 2)

    if ungban_time > 60:
        ungban_time = round((ungban_time / 60), 2)
        await message.reply_text(f"Global ban removed. Took {ungban_time} min")
    else:
        await message.reply_text(f"Global ban removed. Took {ungban_time} sec")


@support_plus
@on_message(filters.command("gbanlist"), chained=True)
async def gbanlist(client, message: Message):
    banned_users = sql.get_gban_list()

    if not banned_users:
        await message.reply_text(
            "There are no globally banned users.",
        )
        return

    banfile = "Globally banned users:\n"
    for user in banned_users:
        banfile += f"[x] {user['name']} - {user['user_id']}\n"
        if user["reason"]:
            banfile += f"Reason: {user['reason']}\n"

    with BytesIO(str.encode(banfile)) as output:
        output.name = "gbanlist.txt"
        await message.reply_document(
            document=output,
            caption="Globally banned users.",
        )


@check_admin(is_user=True)
@on_message(GROUPS, filters.command("antispam"), chained=True)
async def gbanstat(client, message: Message):
    args = message.command[1:] if message.command else []
    if len(args) > 0:
        if args[0].lower() in ["on", "yes"]:
            sql.enable_gbans(message.chat.id)
            await message.reply_text(
                "Antispam is enabled. The bot now protects this group from remote threats."
            )
        elif args[0].lower() in ["off", "no"]:
            sql.disable_gbans(message.chat.id)
            await message.reply_text(
                "Antispam is disabled. The bot no longer protects this group from remote threats."
            )
    else:
        await message.reply_text(
            "Provide a setting: on/off or yes/no.\n\n"
            "Current setting: {}\n"
            "When enabled, global bans also apply in this group. "
            "When disabled, they do not.".format(sql.does_chat_gban(message.chat.id)),
        )


def __stats__():
    return f"• {sql.num_gbanned_users()} globally banned users."


def __user_info__(user_id):
    is_gbanned = sql.is_user_gbanned(user_id)
    text = "Malicious: <b>{}</b>"
    if user_id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN):
        return ""
    if user_id == BOT_ID:
        return ""
    if int(user_id) in DRAGONS:
        return ""
    if is_gbanned:
        text = text.format("Yes")
        user = sql.get_gbanned_user(user_id)
        if user.reason:
            text += f"\n<b>Reason:</b> <code>{html.escape(user.reason)}</code>"
        text += f"\n<b>Appeal Chat:</b> @{SUPPORT_CHAT}"
    else:
        text = text.format("???")
    return text


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return f"This chat enforces global bans: `{sql.does_chat_gban(chat_id)}`."


__help__ = """
Admins only:
/antispam <on/off/yes/no>: Toggle antispam or show the current setting.

Anti-spam bans spammers across all groups that use it and removes spam floods quickly.

Users can appeal a global ban or report spammers at @hydraX2support.
"""


__mod_name__ = "Anti-Spam"
