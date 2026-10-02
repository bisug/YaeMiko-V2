import asyncio
import html
import time

from aiogram import F
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import Database.sql.raid_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.gate import chain
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


async def _resolve(message: Message, command: CommandObject):
    """Return (chat, chat_id) for the target group, honouring connections.

    Returns (None, None) after replying when there is no group to act on.
    """
    user = message.from_user
    conn = await connected(bot, message, message.chat, user.id, need_admin=True)
    if conn:
        return await bot.get_chat(conn), conn
    if message.chat.type == ChatType.PRIVATE:
        await message.reply("This command is meant to be used in a group.")
        return None, None
    return message.chat, message.chat.id


@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def antiraid(message: Message, command: CommandObject) -> str:
    chat, chat_id = await _resolve(message, command)
    if chat is None:
        return ""

    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        active, raid_time, action_time, auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply(
            f"<b>AntiRaid is currently {'enabled' if active else 'disabled'}.</b>\n\n"
            f"Raid duration: <code>{format_duration(raid_time)}</code>"
            f"\nBan duration: <code>{format_duration(action_time)}</code>"
            f"\nAuto AntiRaid: <code>{f'{auto} joins/min' if auto else 'off'}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Enable AntiRaid" if not active else "Disable AntiRaid",
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
        await message.reply("Disabled AntiRaid. New joins are no longer banned.")
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
    await message.reply(
        f"Enabled AntiRaid for <code>{shown}</code>. New members will be banned on join.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Has <b>enabled</b> AntiRaid for <code>{shown}</code>."
    )


@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def raidtime(message: Message, command: CommandObject) -> str:
    chat, chat_id = await _resolve(message, command)
    if chat is None:
        return ""

    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        _active, raid_time, *_ = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply(
            f"AntiRaid stays enabled for <code>{format_duration(raid_time)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    shown = format_duration(expiry - int(time.time()))
    await asyncio.to_thread(sql.set_raid_time, chat_id, expiry - int(time.time()))
    await message.reply(
        f"AntiRaid will now stay enabled for <code>{shown}</code>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set AntiRaid duration to <code>{shown}</code>."
    )


@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def raidactiontime(message: Message, command: CommandObject) -> str:
    chat, chat_id = await _resolve(message, command)
    if chat is None:
        return ""

    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        _active, _raid_time, action_time, _auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply(
            f"Raiders are banned for <code>{format_duration(action_time)}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    shown = format_duration(expiry - int(time.time()))
    await asyncio.to_thread(sql.set_action_time, chat_id, expiry - int(time.time()))
    await message.reply(
        f"Raiders will now be banned for <code>{shown}</code>.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set AntiRaid ban duration to <code>{shown}</code>."
    )


@check_admin(permission="can_restrict_members", is_both=True)
@loggable
@typing_action
async def autoantiraid(message: Message, command: CommandObject) -> str:
    chat, chat_id = await _resolve(message, command)
    if chat is None:
        return ""

    user = message.from_user
    args = command.args.split() if command.args else []

    if not args:
        _active, _raid_time, _action_time, auto = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
        await message.reply(
            f"Auto AntiRaid is <code>{f'{auto} joins/min' if auto else 'off'}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    if args[0].lower() in OFF_WORDS:
        await asyncio.to_thread(sql.set_auto_antiraid, chat_id, 0)
        await message.reply("Disabled automatic AntiRaid.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#ANTIRAID\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Has <b>disabled</b> automatic AntiRaid."
        )

    if not args[0].isdigit():
        await message.reply(
            "Give me a number of joins per minute, or `off`.",
            parse_mode=ParseMode.HTML,
        )
        return ""

    threshold = int(args[0])
    await asyncio.to_thread(sql.set_auto_antiraid, chat_id, threshold)
    await asyncio.to_thread(sql.clear_joins, chat_id)
    await message.reply(
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


async def _raid_join(message: Message) -> str:
    """Ban a newly joined member while the raid window is open.

    Admins, approved users, bots and anonymous admins are skipped: a raid punishes
    drive-by joins, and an admin cannot be banned by a bot anyway.
    """
    chat = message.chat
    member = message.new_chat_member
    if member is None or chat.type == ChatType.PRIVATE:
        return ""

    new_user = member.user
    if new_user is None or new_user.is_bot:
        return ""
    if new_user.id in (ChatID.SERVICE_CHAT, ChatID.ANONYMOUS_ADMIN, bot.id):
        return ""

    active, _raid_time, action_time, auto = await asyncio.to_thread(
        sql.get_raid_setting, chat.id
    )
    if auto:
        joins = await asyncio.to_thread(sql.record_join, chat.id)
        if not active and joins > auto:
            await asyncio.to_thread(sql.set_raid, chat.id)
            active = True
            await message.reply(
                f"\u26a0\ufe0f {joins} users joined in under a minute."
                f" AntiRaid has been <b>enabled</b>.",
                parse_mode=ParseMode.HTML,
            )
    if not active:
        return ""
    if await asyncio.to_thread(is_approved, chat.id, new_user.id):
        return ""

    try:
        status = await bot.get_chat_member(chat.id, new_user.id)
    except Exception:
        LOGGER.warning("AntiRaid could not read membership of %s in %s", new_user.id, chat.id)
        return ""
    if status.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
        return ""

    try:
        await bot.ban_chat_member(
            chat.id, new_user.id, until_date=int(time.time()) + int(action_time)
        )
    except Exception:
        LOGGER.exception("AntiRaid could not ban a raider in %s", chat.id)
        return ""

    shown = format_duration(action_time)
    await message.reply(
        f"\U0001f512 <b>AntiRaid:</b> {mention_html(new_user.id, new_user.first_name)}"
        f" was banned for {shown} while AntiRaid is active.",
        parse_mode=ParseMode.HTML,
    )
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#ANTIRAID\n"
        f"<b>Banned:</b> {mention_html(new_user.id, new_user.first_name)}"
        f" [<code>{new_user.id}</code>]\n"
        f"<b>Reason:</b> Joined during an active AntiRaid."
    )


async def antiraid_button(message, query) -> str:
    """Toggle the raid from the /antiraid inline button."""
    chat_id = int(query.data.split("_")[1])
    action = query.data.rsplit("_", 1)[1]

    try:
        status = await bot.get_chat_member(chat_id, query.from_user.id)
    except Exception:
        await query.answer("I can't see that chat anymore.", show_alert=True)
        return ""
    if status.status not in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
        await query.answer("You need to be an admin to do this.", show_alert=True)
        return ""

    if action == "on":
        await asyncio.to_thread(sql.set_raid, chat_id)
        _active, raid_time, *_ = await asyncio.to_thread(
            sql.get_raid_setting, chat_id
        )
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

dp.message.register(chain(antiraid), *disableable("antiraid"))
dp.message.register(chain(raidtime), *disableable("raidtime"))
dp.message.register(chain(raidactiontime), *disableable("raidactiontime"))
dp.message.register(chain(autoantiraid), *disableable("autoantiraid"))
dp.message.register(chain(_raid_join), F.new_chat_member)
dp.callback_query.register(
    chain(antiraid_button), F.data.regexp(r"^antiraid_-?\d+_(?:on|off)$")
)
