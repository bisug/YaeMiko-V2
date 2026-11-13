import asyncio
import html
import time
from datetime import datetime, timezone

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import Database.sql.raid_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import LOGGER
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.connection import connected
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.parser import mention_html

ON_WORDS = ("on", "yes", "true", "enable", "1")
OFF_WORDS = ("off", "no", "false", "disable", "0")


def format_duration(seconds: int) -> str:
    """Human-readable duration, using the same m/h/d/w units the input accepts."""
    seconds = int(seconds)
    for size, unit in ((604800, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if seconds and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


async def _resolve(client, message: Message):
    """Return (chat, chat_id) for the target group, honouring connections.

    Returns (None, None) after replying when there is no group to act on.
    """
    user = message.from_user
    conn = await connected(client, message, message.chat, user.id, need_admin=True)
    if conn:
        return await client.get_chat(conn), conn
    if message.chat.type == ChatType.PRIVATE:
        await message.reply_text("This command is meant to be used in a group.")
        return None, None
    return message.chat, message.chat.id


@on_message(filters.command("antiraid"), chained=True)
@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def antiraid(client, message: Message) -> str:
    chat, chat_id = await _resolve(client, message)
    if chat is None:
        return ""

    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []

    if not args:
        active, raid_time, action_time, auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply_text(
            f"<b>AntiRaid is currently {'enabled' if active else 'disabled'}.</b>\n\n"
            f"Raid duration: <code>{format_duration(raid_time)}</code>"
            f"\nBan duration: <code>{format_duration(action_time)}</code>"
            f"\nAuto AntiRaid: <code>{f'{auto} joins/min' if auto else 'off'}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Enable AntiRaid"
                            if not active
                            else "Disable AntiRaid",
                            callback_data=f"antiraid_{chat_id}_"
                            f"{'off' if active else 'on'}",
                        )
                    ]
                ]
            ),
        )
        return ""

    if args[0].lower() in OFF_WORDS:
        await asyncio.to_thread(sql.rem_raid, chat_id)
        await asyncio.to_thread(sql.clear_joins, chat_id)
        await message.reply_text("Disabled AntiRaid. New joins are no longer banned.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#ANTIRAID\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has <b>disabled</b> AntiRaid."
        )

    # "/antiraid 3h" enables for a custom window; bare on/yes/true uses raidtime.
    duration = None
    if args[0].lower() not in ON_WORDS:
        expiry = await extract_time(message, args[0])
        if not expiry:
            return ""
        duration = expiry - int(time.time())

    await asyncio.to_thread(sql.set_raid, chat_id, duration)
    _active, raid_time, *_ = await asyncio.to_thread(sql.get_raid_setting, chat_id)
    shown = format_duration(duration or raid_time)
    await message.reply_text(
        f"Enabled AntiRaid for <code>{shown}</code>. New members will be banned on join.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Has <b>enabled</b> AntiRaid for <code>{shown}</code>."
    )


@on_message(filters.command("raidtime"), chained=True)
@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def raidtime(client, message: Message) -> str:
    chat, chat_id = await _resolve(client, message)
    if chat is None:
        return ""

    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []

    if not args:
        _active, raid_time, *_ = await asyncio.to_thread(sql.get_raid_setting, chat_id)
        await message.reply_text(
            f"AntiRaid stays enabled for <code>{format_duration(raid_time)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    shown = format_duration(expiry - int(time.time()))
    await asyncio.to_thread(sql.set_raid_time, chat_id, expiry - int(time.time()))
    await message.reply_text(
        f"AntiRaid will now stay enabled for <code>{shown}</code>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set AntiRaid duration to <code>{shown}</code>."
    )


@on_message(filters.command("raidactiontime"), chained=True)
@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def raidactiontime(client, message: Message) -> str:
    chat, chat_id = await _resolve(client, message)
    if chat is None:
        return ""

    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []

    if not args:
        _active, _raid_time, action_time, _auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply_text(
            f"Raiders are banned for <code>{format_duration(action_time)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    shown = format_duration(expiry - int(time.time()))
    await asyncio.to_thread(sql.set_action_time, chat_id, expiry - int(time.time()))
    await message.reply_text(
        f"Raiders will now be banned for <code>{shown}</code>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set AntiRaid ban duration to <code>{shown}</code>."
    )


@on_message(filters.command("autoantiraid"), chained=True)
@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def autoantiraid(client, message: Message) -> str:
    chat, chat_id = await _resolve(client, message)
    if chat is None:
        return ""

    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []

    if not args:
        _active, _raid_time, _action_time, auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply_text(
            f"Auto AntiRaid is <code>{f'{auto} joins/min' if auto else 'off'}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    if args[0].lower() in OFF_WORDS:
        await asyncio.to_thread(sql.set_auto_antiraid, chat_id, 0)
        await message.reply_text("Disabled automatic AntiRaid.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#ANTIRAID\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has <b>disabled</b> automatic AntiRaid."
        )

    if not args[0].isdigit():
        await message.reply_text(
            "Give me a number of joins per minute, or `off`.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    threshold = int(args[0])
    await asyncio.to_thread(sql.set_auto_antiraid, chat_id, threshold)
    await asyncio.to_thread(sql.clear_joins, chat_id)
    await message.reply_text(
        f"AntiRaid will enable itself when more than <code>{threshold}</code>"
        f" users join within a minute.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set automatic AntiRaid to <code>{threshold}</code> joins/min."
    )


@on_message(filters.group & filters.new_chat_members, chained=True)
@loggable
async def _raid_join(client, message: Message) -> str:
    """Ban a newly joined member while the raid window is open.

    Admins, approved users, bots and anonymous admins are skipped: a raid punishes
    drive-by joins, and an admin cannot be banned by a bot anyway.
    """
    chat = message.chat
    if not message.new_chat_members or chat.type == ChatType.PRIVATE:
        return ""

    active, _raid_time, action_time, auto = await asyncio.to_thread(
        sql.get_raid_setting, chat.id
    )
    if auto:
        joins = await asyncio.to_thread(sql.record_join, chat.id)
        if not active and joins > auto:
            await asyncio.to_thread(sql.set_raid, chat.id)
            active = True
            await message.reply_text(
                f"\u26a0\ufe0f {joins} users joined in under a minute."
                f" AntiRaid has been <b>enabled</b>.",
                parse_mode=ParseMode.HTML,
            )
    if not active:
        return ""

    log_entries = []
    my_id = (
        (await client.get_me()).id
        if getattr(client, "me", None) is None
        else client.me.id
    )
    for new_user in message.new_chat_members:
        if new_user is None or new_user.is_bot:
            continue
        if new_user.id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN, my_id):
            continue
        if await asyncio.to_thread(is_approved, chat.id, new_user.id):
            continue

        try:
            status = await client.get_chat_member(chat.id, new_user.id)
        except Exception:
            LOGGER.warning(
                "AntiRaid could not read membership of %s in %s", new_user.id, chat.id
            )
            continue
        if status.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            continue

        try:
            ban_until = datetime.fromtimestamp(
                int(time.time()) + int(action_time), timezone.utc
            )
            await client.ban_chat_member(chat.id, new_user.id, until_date=ban_until)
        except Exception:
            LOGGER.exception("AntiRaid could not ban a raider in %s", chat.id)
            continue

        shown = format_duration(action_time)
        await message.reply_text(
            f"\U0001f512 <b>AntiRaid:</b> {mention_html(new_user.id, new_user.first_name)}"
            f" was banned for {shown} while AntiRaid is active.",
            parse_mode=ParseMode.HTML,
        )
        log_entries.append(
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#ANTIRAID\n"
            f"<b>Banned:</b> {mention_html(new_user.id, new_user.first_name)}"
            f" [<code>{new_user.id}</code>]\n"
            f"<b>Reason:</b> Joined during an active AntiRaid."
        )
    return "\n\n".join(log_entries)


@on_callback(filters.regex(r"^antiraid_-?\d+_(?:on|off)$"), chained=True)
async def antiraid_button(client, query: CallbackQuery) -> str:
    """Toggle the raid from the /antiraid inline button."""
    chat_id = int(query.data.split("_")[1])
    action = query.data.rsplit("_", 1)[1]

    try:
        status = await client.get_chat_member(chat_id, query.from_user.id)
    except Exception:
        await query.answer("I can't see that chat anymore.", show_alert=True)
        return ""
    if status.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
        await query.answer("You need to be an admin to do this.", show_alert=True)
        return ""

    if action == "on":
        await asyncio.to_thread(sql.set_raid, chat_id)
        _active, raid_time, *_ = await asyncio.to_thread(sql.get_raid_setting, chat_id)
        detail = f"AntiRaid is enabled for <code>{format_duration(raid_time)}</code>."
    else:
        await asyncio.to_thread(sql.rem_raid, chat_id)
        await asyncio.to_thread(sql.clear_joins, chat_id)
        detail = "AntiRaid is disabled. New joins are no longer banned."

    await query.message.edit_text(
        f"<b>AntiRaid is now {action}ed.</b>\n\n{detail}",
        parse_mode=ParseMode.HTML,
    )
    await query.answer(detail)
    return ""


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    active, raid_time, action_time, auto = sql.get_raid_setting(chat_id)
    return (
        f"This chat has AntiRaid <b>{'enabled' if active else 'disabled'}</b>;"
        f" duration `{format_duration(raid_time)}`, ban `{format_duration(action_time)}`,"
        f" auto `{auto or 'off'}`."
    )


__mod_name__ = "ANTIRAID"

__help__ = """
\u27a1 Some spammers join a group in bulk to flood it with spam. AntiRaid bans every new
member while it is enabled, so you can sit the raid out instead of fighting it live.

\u27a1 *Admin commands:*

\u00bb /antiraid: Check the current state, or toggle it with the button.
\u00bb /antiraid on: Enable AntiRaid for the duration set by `/raidtime`.
\u00bb /antiraid off: Disable AntiRaid immediately.
\u00bb /antiraid <time>: Enable AntiRaid for a custom duration, eg `3h`.

\u00bb /raidtime <time>: How long AntiRaid stays on when enabled. Default 6h.
\u00bb /raidactiontime <time>: How long a raider is banned for. Default 1h.

\u00bb /autoantiraid <number>: Enable AntiRaid automatically when more than this many
users join within a minute.
\u00bb /autoantiraid off: Disable automatic AntiRaid.

\u27a1 Durations accept `m`, `h`, `d` or `w` (eg `90m`, `12h`, `3d`, `2w`).
"""
