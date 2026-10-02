import html
import re
from typing import Optional

from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from Database.sql import warns_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import BAN_STICKER, bot, dp
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin, is_user_admin
from Mikobot.plugins.helper_funcs.extraction import (
    extract_text,
    extract_user,
    extract_user_and_text,
)
from Mikobot.plugins.helper_funcs.misc import split_message
from Mikobot.plugins.helper_funcs.string_handling import split_quotes
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.consts import MessageLimit
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

CURRENT_WARNING_FILTER_STRING = "<b>Current warning filters in this chat:</b>\n"


# Not async
async def warn(
    user: User,
    chat: Chat,
    reason: str,
    message: Message,
    warner: User = None,
) -> str:
    if await is_user_admin(chat, user.id):
        await message.answer("Damn admins, They are too far to be Warned")
        return

    if warner:
        warner_tag = mention_html(warner.id, warner.first_name)
    else:
        warner_tag = "Automated warn filter."

    limit, soft_warn = sql.get_warn_setting(chat.id)
    num_warns, reasons = sql.warn_user(user.id, chat.id, reason)
    if num_warns >= limit:
        sql.reset_warns(user.id, chat.id)
        if soft_warn:  # punch
            # PTB's chat.unban_member returned a truthy result and was not
            # awaited; aiogram raises, so this has to be awaited to actually kick.
            await bot.unban_chat_member(chat.id, user.id)
            reply = (
                f"<code>❕</code><b>Kick Event</b>\n"
                f"<code> </code><b>•  User:</b> {mention_html(user.id, user.first_name)}\n"
                f"<code> </code><b>•  Count:</b> {limit}"
            )

        else:  # ban
            await bot.ban_chat_member(chat.id, user.id)
            reply = (
                f"<code>❕</code><b>Ban Event</b>\n"
                f"<code> </code><b>•  User:</b> {mention_html(user.id, user.first_name)}\n"
                f"<code> </code><b>•  Count:</b> {limit}"
            )

        for warn_reason in reasons:
            reply += f"\n - {html.escape(warn_reason)}"

        await message.answer_sticker(BAN_STICKER)  # Saitama's sticker
        keyboard = None
        log_reason = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#WARN_BAN\n"
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
                        text="🔘 Remove warn",
                        callback_data="rm_warn({})".format(user.id),
                     style=ButtonStyle.DANGER),
                ],
            ],
        )

        reply = (
            f"<code>❕</code><b>Warn Event</b>\n"
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

    try:
        await message.answer(
            reply, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            await message.answer(
                reply,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,

            )
        else:
            raise
    return log_reason


@loggable
async def button(query: CallbackQuery) -> str:
    user: Optional[User] = query.from_user
    match = re.fullmatch(r"rm_warn\((-?\d+)\)", query.data)
    if not match:
        await query.answer("Invalid callback data.", show_alert=True)
        return
    try:
        user_id = int(match.group(1))
    except ValueError:
        await query.answer("Invalid callback data.", show_alert=True)
        return
    chat: Optional[Chat] = query.message.chat
    chat_member = await bot.get_chat_member(chat.id, user.id)
    if chat_member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        pass
    else:
        await query.answer("You need to be admin to do this!")
        return
    res = sql.remove_warn(user_id, chat.id)
    if res:
        await query.message.edit_text(
            "Warn removed by {}.".format(mention_html(user.id, user.first_name)),
            parse_mode=ParseMode.HTML,
        )
        user_member = await bot.get_chat_member(chat.id, user_id)
        await query.answer("Warn removed.")
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#UNWARN\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>User:</b> {mention_html(user_member.user.id, user_member.user.first_name)}"
        )
    else:
        await query.message.edit_text(
            "User already has no warns.",
            parse_mode=ParseMode.HTML,
        )
        await query.answer()

    return ""


@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def warn_user(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat: Optional[Chat] = message.chat
    warner: Optional[User] = message.from_user

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
            and message.reply_to_message.from_user.id == user_id
        ):
            return await warn(
                message.reply_to_message.from_user,
                chat,
                reason,
                message.reply_to_message,
                warner,
            )
        else:
            member = await bot.get_chat_member(chat.id, user_id)
            return await warn(member.user, chat, reason, message, warner)
    else:
        await message.answer("That looks like an invalid User ID to me.")
    return ""


@loggable
@check_admin(is_both=True)
async def reset_warns(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat: Optional[Chat] = message.chat
    user: Optional[User] = message.from_user

    user_id = await extract_user(message, args)

    if user_id:
        sql.reset_warns(user_id, chat.id)
        await message.answer("Warns have been reset!")
        warned = await chat.get_member(user_id).user
        return (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#RESETWARNS\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>User:</b> {mention_html(warned.id, warned.first_name)}"
        )
    else:
        await message.answer("No user has been designated!")
    return ""


async def warns(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat: Optional[Chat] = message.chat
    user_id = await extract_user(message, args) or message.from_user.id
    result = sql.get_warns(user_id, chat.id)

    if result and result[0] != 0:
        num_warns, reasons = result
        limit, soft_warn = sql.get_warn_setting(chat.id)

        if reasons:
            text = (
                f"This user has {num_warns}/{limit} warns, for the following reasons:"
            )
            for reason in reasons:
                text += f"\n • {html.escape(reason)}"

            msgs = split_message(text)
            for msg in msgs:
                await message.reply(msg)
        else:
            await message.reply(
                f"User has {num_warns}/{limit} warns, but no reasons for any of them.",
            )
    else:
        await message.reply("This user doesn't have any warns!")


# Dispatcher handler stop - do not async
@check_admin(is_user=True)
async def add_warn_filter(message: Message, command: CommandObject):
    chat: Optional[Chat] = message.chat
    msg: Optional[Message] = message

    args = msg.text.split(
        None,
        1,
    )  # use python's maxsplit to separate Cmd, keyword, and reply_text

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) >= 2:
        # set trigger -> lower, so as to avoid adding duplicate filters with different cases
        keyword = extracted[0].lower()
        content = extracted[1]

    else:
        return

    # aiogram has no per-handler removal, and the filter table is the source of
    # truth, so re-adding a keyword overwrites the previous reply at send time.
    sql.add_warn_filter(chat.id, keyword, content)

    await message.reply(f"Warn handler added for '{keyword}'!")
    raise SkipHandler()


@check_admin(is_user=True)
async def remove_warn_filter(message: Message, command: CommandObject):
    chat: Optional[Chat] = message.chat
    msg: Optional[Message] = message

    args = msg.text.split(
        None,
        1,
    )  # use python's maxsplit to separate Cmd, keyword, and reply_text

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) < 1:
        return

    to_remove = extracted[0]

    chat_filters = sql.get_chat_warn_triggers(chat.id)

    if not chat_filters:
        await msg.answer("No warning filters are active here!")
        return

    for filt in chat_filters:
        if filt == to_remove:
            sql.remove_warn_filter(chat.id, to_remove)
            await msg.answer("Okay, I'll stop warning people for that.")
            raise SkipHandler()

    await msg.answer(
        "That's not a current warning filter - run /warnlist for all active warning filters.",
    )


async def list_warn_filters(message: Message, command: CommandObject):
    chat: Optional[Chat] = message.chat
    all_handlers = sql.get_chat_warn_triggers(chat.id)

    if not all_handlers:
        await message.reply("No warning filters are active here!")
        return

    filter_list = CURRENT_WARNING_FILTER_STRING
    for keyword in all_handlers:
        entry = f" - {html.escape(keyword)}\n"
        if len(entry) + len(filter_list) > MessageLimit.MAX_TEXT_LENGTH:
            await message.reply(
                filter_list, parse_mode=ParseMode.HTML
            )
            filter_list = entry
        else:
            filter_list += entry

    if filter_list != CURRENT_WARNING_FILTER_STRING:
        await message.reply(
            filter_list, parse_mode=ParseMode.HTML
        )


@loggable
async def reply_filter(message: Message) -> str:
    chat: Optional[Chat] = message.chat
    message: Optional[Message] = message
    user: Optional[User] = message.from_user

    if not user:  # Ignore channel
        return

    if user.id == 777000:
        return
    if is_approved(chat.id, user.id):
        return
    chat_warn_filters = sql.get_chat_warn_triggers(chat.id)
    to_match = await extract_text(message)
    if not to_match:
        return ""

    for keyword in chat_warn_filters:
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            user: Optional[User] = message.from_user
            warn_filter = sql.get_warn_filter(chat.id, keyword)
            return await warn(user, chat, warn_filter.reply, message)
    return ""


@check_admin(is_user=True)
@loggable
async def set_warn_limit(message: Message, command: CommandObject) -> str:
    args = command.args.split() if command.args else []
    chat: Optional[Chat] = message.chat
    user: Optional[User] = message.from_user
    user: Optional[User] = message.from_user
    msg: Optional[Message] = message

    if args:
        if args[0].isdigit():
            if int(args[0]) < 3:
                await msg.answer("The minimum warn limit is 3!")
            else:
                sql.set_warn_limit(chat.id, int(args[0]))
                await msg.answer("Updated the warn limit to {}".format(args[0]))
                return (
                    f"<b>{html.escape(chat.title)}:</b>\n"
                    f"#SET_WARN_LIMIT\n"
                    f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                    f"Set the warn limit to <code>{args[0]}</code>"
                )
        else:
            await msg.answer("Give me a number as an arg!")
    else:
        limit, soft_warn = sql.get_warn_setting(chat.id)

        await msg.answer("The current warn limit is {}".format(limit))
    return ""


@check_admin(is_user=True)
async def set_warn_strength(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat: Optional[Chat] = message.chat
    user: Optional[User] = message.from_user
    msg: Optional[Message] = message

    if args:
        if args[0].lower() in ("on", "yes"):
            sql.set_warn_strength(chat.id, False)
            await msg.answer("Too many warns will now result in a Ban!")
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has enabled strong warns. Users will be seriously Kicked.(banned)"
            )

        elif args[0].lower() in ("off", "no"):
            sql.set_warn_strength(chat.id, True)
            await msg.answer(
                "Too many warns will now result in a normal Kick! Users will be able to join again after.",
            )
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"Has disabled strong Kicks. I will use normal kick on users."
            )

        else:
            await msg.answer("I only understand on/yes/no/off!")
    else:
        limit, soft_warn = sql.get_warn_setting(chat.id)
        if soft_warn:
            await msg.answer(
                "Warns are currently set to *kick* users when they exceed the limits.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await msg.answer(
                "Warns are currently set to *Ban* users when they exceed the limits.",
                parse_mode=ParseMode.MARKDOWN,
            )
    return ""


def __stats__():
    return (
        f"• {sql.num_warns()} overall warns, across {sql.num_warn_chats()} chats.\n"
        f"• {sql.num_warn_filters()} warn filters, across {sql.num_warn_filter_chats()} chats."
    )


async def __import_data__(chat_id, data, message):
    for user_id, count in data.get("warns", {}).items():
        for x in range(int(count)):
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
» /warns <userhandle>: get a user's number, and reason, of warns.

» /warnlist: list of all current warning filters

➠ *Admins only:*

» /warn <userhandle>: warn a user. After 3 warns, the user will be banned from the group. Can also be used as a reply.

» /dwarn <userhandle>: warn a user and delete the message. After 3 warns, the user will be banned from the group. Can also be used as a reply.

» /resetwarn <userhandle>: reset the warns for a user. Can also be used as a reply.

» /addwarn <keyword> <reply message>: set a warning filter on a certain keyword. If you want your keyword to \
be a sentence, encompass it with quotes, as such: `/addwarn "very angry" This is an angry user`.

» /nowarn <keyword>: stop a warning filter

» /warnlimit <num>: set the warning limit

» /strongwarn <on/yes/off/no>: If set to on, exceeding the warn limit will result in a ban. Else, will just kick.
"""

# The filter matcher sees every group text message, so it registers first,
# matching PTB's group 9 ordering.
dp.message.register(chain(reply_filter), GROUPS, F.text)
dp.message.register(chain(warn_user), GROUPS, Command(commands=["warn", "dwarn"]))
dp.message.register(chain(reset_warns), GROUPS, Command(commands=["resetwarn", "resetwarns"]))
dp.message.register(chain(warns), GROUPS, *disableable("warns"))
dp.message.register(chain(add_warn_filter), GROUPS, Command("addwarn"))
dp.message.register(chain(remove_warn_filter), GROUPS, Command(commands=["nowarn", "stopwarn"]))
dp.message.register(
    chain(list_warn_filters),
    GROUPS,
    *disableable(["warnlist", "warnfilters"], admin_ok=True),
)
dp.message.register(chain(set_warn_limit), GROUPS, Command("warnlimit"))
dp.message.register(chain(set_warn_strength), GROUPS, Command("strongwarn"))
dp.callback_query.register(chain(button), F.data.regexp(r"^rm_warn\(-?\d+\)$"))
