import asyncio
import html
import re
import time
from datetime import timedelta

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from pyrogram.errors import ReplyMessageIdInvalid, RPCError
from pyrogram.types import (
    CallbackQuery,
    Chat,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from Database.sql import warns_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import BAN_STICKER
from Mikobot import app as client
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin, is_user_admin
from Mikobot.plugins.helper_funcs.extraction import (
    extract_text,
    extract_user,
    extract_user_and_text,
)
from Mikobot.plugins.helper_funcs.misc import split_message
from Mikobot.plugins.helper_funcs.string_handling import extract_time, split_quotes
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import ChatID, MessageLimit
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html

CURRENT_WARNING_FILTER_STRING = "<b>Current warning filters in this chat:</b>\n"


async def warn(
    user: User,
    chat: Chat,
    reason: str,
    message: Message,
    warner: User = None,
    silent: bool = False,
) -> str:
    if await is_user_admin(chat, user.id):
        await message.reply_text("Admins cannot be warned.")
        return

    if warner:
        warner_tag = mention_html(warner.id, warner.first_name)
    else:
        warner_tag = "Automated warn filter."

    limit, soft_warn = sql.get_warn_setting(chat.id)
    mode, mode_value = sql.get_warn_mode(chat.id)
    mode = mode or ("kick" if soft_warn else "ban")
    num_warns, reasons = sql.warn_user(user.id, chat.id, reason)
    if num_warns >= limit:
        sql.reset_warns(user.id, chat.id)
        if mode == "kick":
            await client.unban_chat_member(chat.id, user.id)
        elif mode == "mute":
            await client.restrict_chat_member(
                chat.id, user.id, ChatPermissions(can_send_messages=False)
            )
        elif mode == "tmute":
            await client.restrict_chat_member(
                chat.id,
                user.id,
                ChatPermissions(can_send_messages=False),
                until_date=timedelta(seconds=mode_value),
            )
        elif mode == "tban":
            await client.ban_chat_member(
                chat.id, user.id, until_date=timedelta(seconds=mode_value)
            )
        else:
            await client.ban_chat_member(chat.id, user.id)
        reply = (
            f"<b>{mode.title()} event</b>\n"
            f"<code> </code><b>•  User:</b> {mention_html(user.id, user.first_name)}\n"
            f"<code> </code><b>•  Count:</b> {limit}"
        )

        for warn_reason in reasons:
            reply += f"\n - {html.escape(warn_reason)}"

        if not silent:
            await message.reply_sticker(BAN_STICKER)  # Ban sticker
        keyboard = None
        log_reason = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#WARN_{mode.upper()}\n"
            f"<b>Admin:</b> {warner_tag}\n"
            f"<b>User:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>Reason:</b> {html.escape(reason)}\n"
            f"<b>Counts:</b> <code>{num_warns}/{limit}</code>"
        )

    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Remove warn",
                        callback_data="rm_warn({})".format(user.id),
                        style=ButtonStyle.DANGER,
                    ),
                ],
            ],
        )

        reply = (
            f"<b>Warn event</b>\n"
            f"<code> </code><b>•  User:</b> {mention_html(user.id, user.first_name)}\n"
            f"<code> </code><b>•  Count:</b> {num_warns}/{limit}"
        )
        if reason:
            reply += f"\n<code> </code><b>•  Reason:</b> {html.escape(reason)}"

        log_reason = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#WARN\n"
            f"<b>Admin:</b> {warner_tag}\n"
            f"<b>User:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>Reason:</b> {html.escape(reason)}\n"
            f"<b>Counts:</b> <code>{num_warns}/{limit}</code>"
        )

    if not silent:
        try:
            await message.reply_text(
                reply, reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
        except RPCError as excp:
            if isinstance(excp, ReplyMessageIdInvalid):
                # Reply without quoting, since the original message is gone.
                await message.reply_text(
                    reply,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            else:
                raise
    return log_reason


async def _remove_warn(client, chat, user_id, reply, admin, answer=None) -> str:
    """Remove one warn and report it through a reply or an edited callback text."""
    if not sql.remove_warn(user_id, chat.id):
        await reply("User already has no warns.", parse_mode=ParseMode.HTML)
        if answer:
            await answer()
        return ""

    await reply(
        f"Warn removed by {mention_html(admin.id, admin.first_name)}.",
        parse_mode=ParseMode.HTML,
    )
    if answer:
        await answer("Warn removed.")
    user_member = await client.get_chat_member(chat.id, user_id)
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNWARN\n"
        f"<b>Admin:</b> {mention_html(admin.id, admin.first_name)}\n"
        f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
    )


@on_callback(filters.regex(r"^rm_warn\(-?\d+\)$"), chained=True)
@loggable
async def button(client, query: CallbackQuery) -> str:
    user: User | None = query.from_user
    match = re.fullmatch(r"rm_warn\((-?\d+)\)", query.data)
    if not match:
        await query.answer("Invalid callback data.", show_alert=True)
        return
    try:
        user_id = int(match.group(1))
    except ValueError:
        await query.answer("Invalid callback data.", show_alert=True)
        return
    chat: Chat | None = query.message.chat
    chat_member = await client.get_chat_member(chat.id, user.id)
    if chat_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        pass
    else:
        await query.answer("You need to be an admin to do this.")
        return
    return await _remove_warn(
        client, chat, user_id, query.message.edit_text, user, answer=query.answer
    )


@on_message(GROUPS, filters.command(["warn", "dwarn", "swarn"]), chained=True)
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def warn_user(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    warner: User | None = message.from_user
    silent = message.command[0].lower() == "swarn"

    user_id, reason = await extract_user_and_text(message, args)
    if (
        message.text.startswith("/d")
        and message.reply_to_message
        and not message.reply_to_message.forum_topic_created
    ):
        await message.reply_to_message.delete()
    if user_id:
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == user_id
        ):
            return await warn(
                message.reply_to_message.from_user,
                chat,
                reason,
                message.reply_to_message,
                warner,
                silent=silent,
            )
        else:
            member = await client.get_chat_member(chat.id, user_id)
            return await warn(member.user, chat, reason, message, warner, silent=silent)
    else:
        await message.reply_text("That is not a valid user ID.")
    return ""


@on_message(GROUPS, filters.command(["resetwarn", "resetwarns"]), chained=True)
@loggable
@check_admin(is_both=True)
async def reset_warns(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user: User | None = message.from_user

    user_id = await extract_user(message, args)

    if user_id:
        sql.reset_warns(user_id, chat.id)
        await message.reply_text("Warns have been reset.")
        try:
            warned_member = await client.get_chat_member(chat.id, user_id)
            user_target_text = mention_html(
                warned_member.user.id, warned_member.user.first_name
            )
        except RPCError:
            user_target_text = f"<code>{user_id}</code>"
        admin_text = mention_html(user.id, user.first_name) if user else "Admin"
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#RESETWARNS\n"
            f"<b>Admin:</b> {admin_text}\n"
            f"<b>User:</b> {user_target_text}"
        )
    else:
        await message.reply_text("No user specified.")
    return ""


@on_message(GROUPS, *disableable("warns"), chained=True)
async def warns(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user_id = await extract_user(message, args) or (
        message.from_user.id if message.from_user else None
    )
    if not user_id:
        return
    result = sql.get_warns(user_id, chat.id)

    if result and result[0] != 0:
        num_warns, reasons = result
        limit, soft_warn = sql.get_warn_setting(chat.id)

        if reasons:
            text = f"This user has {num_warns}/{limit} warns, for these reasons:"
            for reason in reasons:
                text += f"\n • {html.escape(reason)}"

            msgs = split_message(text)
            for msg in msgs:
                await message.reply_text(msg)
        else:
            await message.reply_text(
                f"User has {num_warns}/{limit} warns, with no reasons recorded.",
            )
    else:
        await message.reply_text("This user has no warns.")


@on_message(GROUPS, filters.command("warnings"), chained=True)
async def warn_config(client, message: Message):
    chat: Chat | None = message.chat
    limit, soft_warn = sql.get_warn_setting(chat.id)
    mode, mode_value = sql.get_warn_mode(chat.id)
    mode = mode or ("kick" if soft_warn else "ban")
    if mode in ("tban", "tmute"):
        mode = f"{mode} ({mode_value}s)"
    expiry = sql.get_warn_time(chat.id)

    await message.reply_text(
        f"Warn configuration for this chat:\n"
        f"Limit: {limit}\n"
        f"Mode: {mode}\n"
        f"Expiry: {f'{expiry} seconds' if expiry else 'off'}",
    )


@on_message(GROUPS, filters.command("rmwarn"), chained=True)
@loggable
@check_admin(is_both=True)
async def remove_warn_user(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    admin: User | None = message.from_user

    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text("That is not a valid user ID.")
        return ""

    # Keep the same admin check, wording and log entry as the remove button.
    return await _remove_warn(client, chat, user_id, message.reply_text, admin)


@on_message(GROUPS, filters.command("addwarn"), chained=True)
@check_admin(is_user=True)
async def add_warn_filter(client, message: Message):
    chat: Chat | None = message.chat
    msg: Message | None = message

    args = msg.text.split(
        None,
        1,
    )

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) >= 2:
        keyword = extracted[0].lower()
        content = extracted[1]
    else:
        return

    sql.add_warn_filter(chat.id, keyword, content)
    await message.reply_text(f"Warn filter added for '{keyword}'.")


@on_message(GROUPS, filters.command(["nowarn", "stopwarn"]), chained=True)
@check_admin(is_user=True)
async def remove_warn_filter(client, message: Message):
    chat: Chat | None = message.chat
    msg: Message | None = message

    args = msg.text.split(
        None,
        1,
    )

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) < 1:
        return

    to_remove = extracted[0]

    chat_filters = sql.get_chat_warn_triggers(chat.id)

    if not chat_filters:
        await msg.reply_text("No warning filters are active here.")
        return

    for filt in chat_filters:
        if filt == to_remove:
            sql.remove_warn_filter(chat.id, to_remove)
            await msg.reply_text("Warning filter removed.")
            return

    await msg.reply_text(
        "That is not an active warning filter. Run /warnlist to see active filters.",
    )


@on_message(
    GROUPS,
    *disableable(["warnlist", "warnfilters"], admin_ok=True),
    chained=True,
)
async def list_warn_filters(client, message: Message):
    chat: Chat | None = message.chat
    all_handlers = sql.get_chat_warn_triggers(chat.id)

    if not all_handlers:
        await message.reply_text("No warning filters are active here.")
        return

    filter_list = CURRENT_WARNING_FILTER_STRING
    for keyword in all_handlers:
        entry = f" - {html.escape(keyword)}\n"
        if len(entry) + len(filter_list) > MessageLimit.MAX_TEXT_LENGTH:
            await message.reply_text(filter_list, parse_mode=ParseMode.HTML)
            filter_list = entry
        else:
            filter_list += entry

    if filter_list != CURRENT_WARNING_FILTER_STRING:
        await message.reply_text(filter_list, parse_mode=ParseMode.HTML)


@on_message(GROUPS, filters.text, chained=True)
@loggable
async def reply_filter(client, message: Message) -> str:
    chat: Chat | None = message.chat
    user: User | None = message.from_user

    if not user:  # Ignore channel
        return

    if user.id == ChatID.SERVICE_CHAT:
        return

    chat_warn_filters = sql.get_chat_warn_triggers(chat.id)
    if not chat_warn_filters:
        return ""

    to_match = await extract_text(message)
    if not to_match:
        return ""

    matching_keyword = None
    for keyword in chat_warn_filters:
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            matching_keyword = keyword
            break

    if not matching_keyword:
        return ""

    if await asyncio.to_thread(is_approved, chat.id, user.id):
        return ""

    warn_filter = await asyncio.to_thread(
        sql.get_warn_filter, chat.id, matching_keyword
    )
    return await warn(user, chat, warn_filter.reply, message)


@on_message(GROUPS, filters.command(["warnlimit", "setwarnlimit"]), chained=True)
@check_admin(is_user=True)
@loggable
async def set_warn_limit(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user: User | None = message.from_user
    msg: Message | None = message

    if args:
        if args[0].isdigit():
            if int(args[0]) < 3:
                await msg.reply_text("The minimum warn limit is 3.")
            else:
                sql.set_warn_limit(chat.id, int(args[0]))
                await msg.reply_text("Warn limit set to {}".format(args[0]))
                return (
                    f"<b>{html.escape(chat.title)}:</b>\n"
                    f"#SET_WARN_LIMIT\n"
                    f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                    f"Set the warn limit to <code>{args[0]}</code>"
                )
        else:
            await msg.reply_text("Provide a number.")
    else:
        limit, soft_warn = sql.get_warn_setting(chat.id)

        await msg.reply_text("The current warn limit is {}".format(limit))
    return ""


@on_message(GROUPS, filters.command("strongwarn"), chained=True)
@check_admin(is_user=True)
async def set_warn_strength(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user: User | None = message.from_user
    msg: Message | None = message

    if args:
        if args[0].lower() in ("on", "yes"):
            sql.set_warn_strength(chat.id, False)
            await msg.reply_text("Too many warns will now result in a ban.")
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has enabled strong warns. Users will be banned."
            )

        elif args[0].lower() in ("off", "no"):
            sql.set_warn_strength(chat.id, True)
            await msg.reply_text(
                "Too many warns will now result in a kick. Users can rejoin.",
            )
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has disabled strong Kicks. I will use normal kick on users."
            )

        else:
            await msg.reply_text("Use on, yes, no, or off.")
    else:
        limit, soft_warn = sql.get_warn_setting(chat.id)
        if soft_warn:
            await msg.reply_text(
                "Warns are currently set to *kick* users who exceed the limit.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await msg.reply_text(
                "Warns are currently set to *ban* users who exceed the limit.",
                parse_mode=ParseMode.MARKDOWN,
            )
    return ""


@on_message(GROUPS, filters.command("setwarnmode"), chained=True)
@check_admin(is_user=True)
@loggable
async def set_warn_mode(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user: User | None = message.from_user
    msg: Message | None = message

    if not args:
        await msg.reply_text("Usage: /setwarnmode <ban|tban|kick|mute|tmute> [time]")
        return ""
    action = args[0].lower()
    if action not in ("ban", "tban", "kick", "mute", "tmute"):
        await msg.reply_text("Use ban, tban, kick, mute, or tmute.")
        return ""

    value = 0
    time_val = None
    if action in ("tban", "tmute"):
        if len(args) < 2:
            await msg.reply_text("Specify a duration, for example 1h.")
            return ""
        time_val = args[1]
        expiry = await extract_time(message, time_val)
        if not expiry:
            return ""
        value = max(1, int(expiry - time.time()))

    sql.set_warn_mode(chat.id, action, value)
    text = f"Warn mode set to {action}"
    if time_val:
        text += f" for {time_val}"
    await msg.reply_text(text)
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#SET_WARN_MODE\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set the warn mode to <code>{action}</code>"
    )


@on_message(GROUPS, filters.command(["setwarntime", "warntime"]), chained=True)
@check_admin(is_user=True)
@loggable
async def set_warn_time(client, message: Message) -> str:
    args = message.command[1:] if len(message.command) > 1 else []
    chat: Chat | None = message.chat
    user: User | None = message.from_user
    msg: Message | None = message

    if not args:
        current = sql.get_warn_time(chat.id)
        state = f"{current} seconds" if current else "off"
        await msg.reply_text(f"Warning expiry is currently {state}.")
        return ""

    arg = args[0].lower()
    if arg in ("off", "no", "never", "0"):
        sql.set_warn_time(chat.id, 0)
        await msg.reply_text("Warning expiry disabled.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#SET_WARN_TIME\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"Disabled warning expiry"
        )

    expiry = await extract_time(message, args[0])
    if not expiry:
        return ""
    duration = max(1, int(expiry - time.time()))
    sql.set_warn_time(chat.id, duration)
    await msg.reply_text(f"Warnings will expire after {args[0]}.")
    return (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#SET_WARN_TIME\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"Set warning expiry to <code>{args[0]}</code>"
    )


def __stats__():
    return (
        f"• {sql.num_warns()} overall warns, across {sql.num_warn_chats()} chats.\n"
        f"• {sql.num_warn_filters()} warn filters, across {sql.num_warn_filter_chats()} chats."
    )


async def __import_data__(chat_id, data, message):
    for user_id, count in data.get("warns", {}).items():
        for _x in range(int(count)):
            sql.warn_user(user_id, chat_id)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    num_warn_filters = sql.num_warn_chat_filters(chat_id)
    limit, soft_warn = sql.get_warn_setting(chat_id)
    return (
        f"This chat has `{num_warn_filters}` warn filters. "
        f"It takes `{limit}` warns before the user gets *{'kicked' if soft_warn else 'banned'}*."
    )


__help__ = """
/warns <userhandle>: Show a user's warn count and reasons.
/warnings: Show the warn limit, action at the limit and warning expiry.
/warnlist: List all active warning filters.

Admin only:
/warn <userhandle>: Warn a user. Users are banned when they reach the warn limit. Can be used as a reply.
/dwarn <userhandle>: Warn a user and delete the message. Users are banned when they reach the warn limit. Can be used as a reply.
/swarn <userhandle>: Warn a user without a public confirmation.
/resetwarn <userhandle>: Reset a user's warns. Can be used as a reply.
/rmwarn <userhandle>: Remove one warn from a user.
/addwarn <keyword> <reply message>: Set a warning filter for a keyword. Quote multi-word keywords, for example /addwarn "very angry" This is an angry user.
/nowarn <keyword>: Remove a warning filter.
/warnlimit <num>, /setwarnlimit <num>: Set the warn limit.
/setwarnmode <ban|tban|kick|mute|tmute> [time]: Choose the action at the warn limit. Timed actions need a duration such as 1h.
/strongwarn <on/yes/off/no>: Ban users who exceed the limit when on. Otherwise, kick them.
/setwarntime <time|off>, /warntime <time|off>: Set when warnings expire, or turn expiry off.
"""

__mod_name__ = "Warns"
