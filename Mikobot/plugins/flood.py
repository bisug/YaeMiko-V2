# <============================================== IMPORTS =========================================================>
import asyncio
import html
import re
import time
from datetime import datetime, timezone

from pyrogram import filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, ChatPermissions, Message

from Database.sql import antiflood_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import app as client
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.connection import connected
from Mikobot.plugins.helper_funcs.alternate import send_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin, is_user_admin
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
@on_message(GROUPS, chained=True)
@loggable
async def check_flood(client, message: Message):
    user = message.from_user
    chat = message.chat
    msg = message
    if not user:
        return ""

    if sql.get_flood_limit(chat.id) == 0:
        return ""

    if await is_user_admin(chat, user.id):
        sql.update_flood(chat.id, None)
        sql.clear_flood_state(chat.id, user.id)
        return ""

    timed = sql.get_flood_timer(chat.id) > 0
    if timed:
        should_ban = sql.update_flood_timer(chat.id, user.id, message.id)
    else:
        should_ban = sql.update_flood(chat.id, user.id)
        if should_ban and sql.get_clearflood(chat.id):
            sql.track_message(chat.id, user.id, message.id)
    if not should_ban:
        return ""

    if await asyncio.to_thread(is_approved, chat.id, user.id):
        sql.update_flood(chat.id, None)
        sql.clear_flood_state(chat.id, user.id)
        return ""

    try:
        getmode, getvalue = await asyncio.to_thread(sql.get_flood_setting, chat.id)
        if getmode == 1:
            await client.ban_chat_member(chat.id, user.id)
            execstrings = "BANNED"
            tag = "BANNED"
        elif getmode == 2:
            await client.unban_chat_member(chat.id, user.id)
            execstrings = "KICKED"
            tag = "KICKED"
        elif getmode == 3:
            await client.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            execstrings = "MUTED"
            tag = "MUTED"
        elif getmode == 4:
            bantime = await extract_time(msg, getvalue)
            if not bantime:
                return ""
            until_dt = datetime.fromtimestamp(bantime, timezone.utc)
            await client.ban_chat_member(chat.id, user.id, until_date=until_dt)
            execstrings = "BANNED for {}".format(getvalue)
            tag = "TBAN"
        elif getmode == 5:
            mutetime = await extract_time(msg, getvalue)
            if not mutetime:
                return ""
            until_dt = datetime.fromtimestamp(mutetime, timezone.utc)
            await client.restrict_chat_member(
                chat.id,
                user.id,
                until_date=until_dt,
                permissions=ChatPermissions(can_send_messages=False),
            )
            execstrings = "MUTED for {}".format(getvalue)
            tag = "TMUTE"
        else:
            execstrings = "MUTED"
            tag = "MUTED"

        if timed or sql.get_clearflood(chat.id):
            tracked = sql.take_flooded_messages(chat.id, user.id)
            for message_id in tracked:
                try:
                    await client.delete_messages(chat.id, message_id)
                except RPCError:
                    continue

        await send_message(
            message,
            "Beep boop! Boop beep!\n{}!".format(execstrings),
        )

        return "<b>{}:</b>\n#{}\n<b>user:</b> {}\nFlooded the group.".format(
            tag,
            html.escape(chat.title),
            mention_html(user.id, user.first_name),
        )

    except RPCError:
        await msg.reply_text(
            "I can't restrict people here, give me permissions first! Until then, I'll disable anti-flood.",
        )
        await asyncio.to_thread(sql.set_flood, chat.id, 0)
        return (
            "<b>{}:</b>"
            "\n#INFO"
            "\nDon't have enough permission to restrict users so automatically disabled anti-flood.".format(
                chat.title,
            )
        )


@on_callback(filters.regex(r"^unmute_flooder\(-?\d+\)$"), chained=True)
@check_admin(permission="can_restrict_members", is_both=True, no_reply=True)
async def flood_button(client, query: CallbackQuery):
    message = query.message
    user = query.from_user
    match = re.fullmatch(r"unmute_flooder\((-?\d+)\)", query.data)
    if not match:
        await query.answer("Invalid callback data.", show_alert=True)
        return
    user_id = int(match.group(1))
    chat = message.chat.id
    try:
        await client.restrict_chat_member(
            chat,
            user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.edit_text(
            f"Unmuted by {mention_html(user.id, user.first_name)}.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await query.answer("Unable to unmute this user.", show_alert=True)
        return

    await query.answer("User unmuted.")


@on_message(GROUPS, filters.command("setflood"), chained=True)
@loggable
@check_admin(is_user=True)
async def set_flood(client, message: Message):
    chat = message.chat
    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []

    conn = await connected(client, message, chat, user.id, need_admin=True)
    if conn:
        chat_id = conn
        chat_obj = await client.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if message.chat.type in (ChatType.PRIVATE, "private"):
            await send_message(
                message,
                "This command is meant to use in a group, not in PM.",
            )
            return ""
        chat_id = message.chat.id
        chat_name = message.chat.title

    if len(args) >= 1:
        val = args[0].lower()
        if val in ["off", "no", "0"]:
            sql.set_flood(chat_id, 0)
            if conn:
                await message.reply_text(
                    "Antiflood has been disabled in {}.".format(chat_name),
                )
            else:
                await message.reply_text("Antiflood has been disabled.")

        elif val.isdigit():
            amount = int(val)
            if amount <= 0:
                sql.set_flood(chat_id, 0)
                if conn:
                    await message.reply_text(
                        "Antiflood has been disabled in {}.".format(chat_name),
                    )
                else:
                    await message.reply_text("Antiflood has been disabled.")
                return (
                    "<b>{}:</b>"
                    "\n#SETFLOOD"
                    "\n<b>Admin:</b> {}"
                    "\nDisable Antiflood.".format(
                        html.escape(chat_name),
                        mention_html(user.id, user.first_name),
                    )
                )

            elif amount <= 3:
                await send_message(
                    message,
                    "Antiflood must be either 0 (disabled) or a number greater than 3!",
                )
                return ""

            else:
                sql.set_flood(chat_id, amount)
                if conn:
                    await message.reply_text(
                        "Antiflood limit has been set to {} in chat: {}".format(
                            amount,
                            chat_name,
                        ),
                    )
                else:
                    await message.reply_text(
                        "Successfully updated antiflood limit to {}!".format(amount),
                    )
                return (
                    "<b>{}:</b>"
                    "\n#SETFLOOD"
                    "\n<b>Admin:</b> {}"
                    "\nSet Antiflood to <code>{}</code>.".format(
                        html.escape(chat_name),
                        mention_html(user.id, user.first_name),
                        amount,
                    )
                )

        else:
            await message.reply_text(
                "Invalid argument, please use a number, 'off', or 'no'."
            )
    else:
        await message.reply_text(
            (
                "Use `/setflood number` to enable antiflood.\n"
                "Or use `/setflood off` to disable antiflood."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    return ""


@on_message(GROUPS, filters.command("flood"), chained=True)
async def flood(client, message: Message):
    chat = message.chat
    user = message.from_user
    msg = message
    conn = await connected(client, message, chat, user.id, need_admin=False)
    if conn:
        chat_id = conn
        chat_obj = await client.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if message.chat.type in (ChatType.PRIVATE, "private"):
            await send_message(
                message,
                "This command is meant to use in a group, not in PM.",
            )
            return
        chat_id = message.chat.id
        chat_name = message.chat.title

    limit = sql.get_flood_limit(chat_id)
    if limit == 0:
        if conn:
            await msg.reply_text(
                "I'm not enforcing any flood control in {}!".format(chat_name),
            )
        else:
            await msg.reply_text("I'm not enforcing any flood control here!")
    else:
        if conn:
            await msg.reply_text(
                "I'm currently restricting members after {} consecutive messages in {}.".format(
                    limit,
                    chat_name,
                ),
            )
        else:
            await msg.reply_text(
                "I'm currently restricting members after {} consecutive messages.".format(
                    limit,
                ),
            )


@on_message(filters.command("setfloodmode"), chained=True)
@check_admin(is_user=True)
async def set_flood_mode(client, message: Message):
    user = message.from_user
    msg = message
    args = message.command[1:] if len(message.command) > 1 else []
    chat = message.chat

    conn = await connected(client, message, chat, user.id, need_admin=True)
    if conn:
        chat = await client.get_chat(conn)
        chat_id = conn
        chat_obj = chat
        chat_name = chat_obj.title
    else:
        if message.chat.type in (ChatType.PRIVATE, "private"):
            await send_message(
                message,
                "This command is meant to use in a group, not in PM.",
            )
            return ""
        chat_id = message.chat.id
        chat_name = message.chat.title

    if args:
        if args[0].lower() == "ban":
            settypeflood = "ban"
            sql.set_flood_strength(chat_id, 1, "0")
        elif args[0].lower() == "kick":
            settypeflood = "kick"
            sql.set_flood_strength(chat_id, 2, "0")
        elif args[0].lower() == "mute":
            settypeflood = "mute"
            sql.set_flood_strength(chat_id, 3, "0")
        elif args[0].lower() == "tban":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for antiflood but you didn't specified time; Try, `/setfloodmode tban <timevalue>`.
Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(message, teks, parse_mode=ParseMode.MARKDOWN)
                return ""
            settypeflood = "tban for {}".format(args[1])
            sql.set_flood_strength(chat_id, 4, str(args[1]))
        elif args[0].lower() == "tmute":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for antiflood but you didn't specified time; Try, `/setfloodmode tmute <timevalue>`.
Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(message, teks, parse_mode=ParseMode.MARKDOWN)
                return ""
            settypeflood = "tmute for {}".format(args[1])
            sql.set_flood_strength(chat_id, 5, str(args[1]))
        else:
            await send_message(
                message,
                "I only understand ban/kick/mute/tban/tmute!",
            )
            return ""
        if conn:
            await msg.reply_text(
                "Exceeding consecutive flood limit will result in {} in {}!".format(
                    settypeflood,
                    chat_name,
                ),
            )
        else:
            await msg.reply_text(
                "Exceeding consecutive flood limit will result in {}!".format(
                    settypeflood,
                ),
            )
        return (
            "<b>{}:</b>\n"
            "<b>Admin:</b> {}\n"
            "Has changed antiflood mode. User will {}.".format(
                settypeflood,
                html.escape(chat.title),
                mention_html(user.id, user.first_name),
            )
        )
    else:
        getmode, getvalue = sql.get_flood_setting(chat.id)
        if getmode == 1:
            settypeflood = "ban"
        elif getmode == 2:
            settypeflood = "kick"
        elif getmode == 3:
            settypeflood = "mute"
        elif getmode == 4:
            settypeflood = "tban for {}".format(getvalue)
        elif getmode == 5:
            settypeflood = "tmute for {}".format(getvalue)
        else:
            settypeflood = "ban"
        if conn:
            await msg.reply_text(
                "Sending more messages than flood limit will result in {} in {}.".format(
                    settypeflood,
                    chat_name,
                ),
            )
        else:
            await msg.reply_text(
                "Sending more messages than flood limit will result in {}.".format(
                    settypeflood,
                ),
            )
    return ""


async def _flood_target(message, user):
    """(chat_id, chat_name) for a group command, honouring connections."""
    conn = await connected(client, message, message.chat, user.id, need_admin=True)
    if conn:
        chat_obj = await client.get_chat(conn)
        return conn, chat_obj.title
    if message.chat.type in (ChatType.PRIVATE, "private"):
        await send_message(
            message, "This command is meant to use in a group, not in PM."
        )
        return None, None
    return message.chat.id, message.chat.title


@on_message(filters.command("setfloodtimer"), chained=True)
@loggable
@check_admin(is_user=True)
async def set_flood_timer(client, message: Message):
    """Act on N messages sent within a window, rather than N in a row."""
    user = message.from_user
    msg = message
    args = message.command[1:] if len(message.command) > 1 else []

    chat_id, chat_name = await _flood_target(message, user)
    if chat_id is None:
        return ""

    if not args:
        current = sql.get_flood_timer(chat_id)
        if not current:
            await send_message(
                msg,
                "Timed antiflood is off; use `/setflood <number>` for consecutive mode.",
            )
            return ""
        await send_message(
            msg,
            "I'm currently acting on more than {} messages within {} seconds here.".format(
                sql.get_flood_limit(chat_id), current
            ),
        )
        return ""

    if len(args) < 2:
        await send_message(
            msg,
            "Use `/setfloodtimer <number> <duration>`, eg `/setfloodtimer 5 10s`.",
        )
        return ""

    if not args[0].isdigit() or int(args[0]) <= 0:
        await send_message(msg, "The message limit must be a number greater than 0.")
        return ""

    expiry = await extract_time(msg, args[1])
    if not expiry:
        return ""
    window = max(1, expiry - int(time.time()))

    amount, seconds = sql.set_flood_timer(chat_id, int(args[0]), window)
    if chat_id != message.chat.id:
        await msg.reply_text(
            "Timed antiflood is now set to {} messages within {} seconds in {}.".format(
                amount, seconds, chat_name
            ),
        )
    else:
        await msg.reply_text(
            "Timed antiflood is now set to {} messages within {} seconds.".format(
                amount, seconds
            ),
        )
    return (
        f"<b>{html.escape(chat_name)}:</b>\n"
        f"#SETFLOODTIMER\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set timed antiflood to <code>{amount}</code> messages within"
        f" <code>{seconds}</code> seconds."
    )


@on_message(filters.command("clearflood"), chained=True)
@loggable
@check_admin(is_user=True)
async def clearflood(client, message: Message):
    """Toggle deleting the whole flooding burst instead of only the excess."""
    user = message.from_user
    msg = message
    args = message.command[1:] if len(message.command) > 1 else []

    chat_id, chat_name = await _flood_target(message, user)
    if chat_id is None:
        return ""

    if not args:
        await send_message(
            msg,
            "Clearflood is currently {}.".format(
                "on" if sql.get_clearflood(chat_id) else "off"
            ),
        )
        return ""

    if args[0].lower() in ("on", "yes", "true", "1"):
        enabled = True
    elif args[0].lower() in ("off", "no", "false", "0"):
        enabled = False
    else:
        await send_message(msg, "Please enter `on` or `off`.")
        return ""

    sql.set_clearflood(chat_id, enabled)
    if chat_id != message.chat.id:
        await msg.reply_text(
            "Clearflood is now {} in {}.".format("on" if enabled else "off", chat_name),
        )
    else:
        await msg.reply_text("Clearflood is now {}.".format("on" if enabled else "off"))

    return (
        f"<b>{html.escape(chat_name)}:</b>\n"
        f"#CLEARFLOOD\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Has turned clearflood <b>{'on' if enabled else 'off'}</b>."
    )


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    limit = sql.get_flood_limit(chat_id)
    if limit == 0:
        return "Not enforcing flood control."
    else:
        return "Antiflood has been set to `{}`.".format(limit)


# <=================================================== HELP ====================================================>


__help__ = """
➠ *Antiflood allows you to take action on users that send more than x messages in a row. Exceeding the set flood will result in restricting that user.*

➠ *Admin Only*

» /flood: Get the current antiflood settings.

» /setflood <number/off/no>: Set the number of messages after which to take action on a user. Set to '0', 'off', or 'no' to disable.

» /setfloodmode <action type>: Choose which action to take on a user who has been flooding. Options: ban/kick/mute/tban/tmute.

» /setfloodtimer <number> <duration>: Act on a user who sends more than `number` messages within `duration`, instead of in a row. Use `/setflood off` to go back to consecutive mode.

» /clearflood on/off: On, deletes every message from the flooding burst instead of only the ones past the limit.
"""

__mod_name__ = "ANTI-FLOOD"
