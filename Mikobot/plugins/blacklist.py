import html
import re

from aiogram import F
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

import Database.sql.blacklist_sql as sql
from Database.sql.approve_sql import is_approved
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin, user_not_admin
from Mikobot.plugins.helper_funcs.extraction import extract_text
from Mikobot.plugins.helper_funcs.misc import split_message
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.plugins.warns import warn
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html


@check_admin(is_user=True)
@typing_action
async def blacklist(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    args = command.args

    conn = await connected(bot, message, chat, user.id, need_admin=False)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if chat.type == ChatType.PRIVATE:
            return
        chat_id = message.chat.id
        chat_name = chat.title

    filter_list = "Current blacklisted words in <b>{}</b>:\n".format(chat_name)

    all_blacklisted = sql.get_chat_blacklist(chat_id)

    if len(args) > 0 and args[0].lower() == "copy":
        for trigger in all_blacklisted:
            filter_list += "<code>{}</code>\n".format(html.escape(trigger))
    else:
        for trigger in all_blacklisted:
            filter_list += " - <code>{}</code>\n".format(html.escape(trigger))

    # for trigger in all_blacklisted:
    #     filter_list += " - <code>{}</code>\n".format(html.escape(trigger))

    split_text = split_message(filter_list)
    for text in split_text:
        if filter_list == "Current blacklisted words in <b>{}</b>:\n".format(
            html.escape(chat_name),
        ):
            await send_message(
                message,
                "No blacklisted words in <b>{}</b>!".format(html.escape(chat_name)),
                parse_mode=ParseMode.HTML,
            )
            return
        await send_message(message, text, parse_mode=ParseMode.HTML)


@check_admin(is_user=True)
@typing_action
async def add_blacklist(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = msg.text.split(None, 1)

    conn = await connected(bot, message, chat, user.id)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            return
        else:
            chat_name = chat.title

    if len(words) > 1:
        text = words[1]
        to_blacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )
        for trigger in to_blacklist:
            sql.add_to_blacklist(chat_id, trigger.lower())

        if len(to_blacklist) == 1:
            await send_message(
                message,
                "Added blacklist <code>{}</code> in chat: <b>{}</b>!".format(
                    html.escape(to_blacklist[0]),
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

        else:
            await send_message(
                message,
                "Added blacklist trigger: <code>{}</code> in <b>{}</b>!".format(
                    len(to_blacklist),
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

    else:
        await send_message(
            message,
            "Tell me which words you would like to add in blacklist.",
        )


@check_admin(is_user=True)
@typing_action
async def unblacklist(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = msg.text.split(None, 1)

    conn = await connected(bot, message, chat, user.id)
    if conn:
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            return
        else:
            chat_name = chat.title

    if len(words) > 1:
        text = words[1]
        to_unblacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )
        successful = 0
        for trigger in to_unblacklist:
            success = sql.rm_from_blacklist(chat_id, trigger.lower())
            if success:
                successful += 1

        if len(to_unblacklist) == 1:
            if successful:
                await send_message(
                    message,
                    "Removed <code>{}</code> from blacklist in <b>{}</b>!".format(
                        html.escape(to_unblacklist[0]),
                        html.escape(chat_name),
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await send_message(
                    message,
                    "This is not a blacklist trigger!",
                )

        elif successful == len(to_unblacklist):
            await send_message(
                message,
                "Removed <code>{}</code> from blacklist in <b>{}</b>!".format(
                    successful,
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

        elif not successful:
            await send_message(
                message,
                "None of these triggers exist so it can't be removed.",
                parse_mode=ParseMode.HTML,
            )

        else:
            await send_message(
                message,
                "Removed <code>{}</code> from blacklist. {} did not exist, "
                "so were not removed.".format(
                    successful,
                    len(to_unblacklist) - successful,
                ),
                parse_mode=ParseMode.HTML,
            )
    else:
        await send_message(
            message,
            "Tell me which words you would like to remove from blacklist!",
        )


@loggable
@check_admin(is_user=True)
@typing_action
async def blacklist_mode(message: Message, command: CommandObject):
    chat = message.chat
    user = message.from_user
    msg = message
    args = command.args

    conn = await connected(bot, message, chat, user.id, need_admin=True)
    if conn:
        chat = await bot.get_chat(conn)
        chat_id = conn
        chat_obj = await bot.get_chat(conn)
        chat_name = chat_obj.title
    else:
        if message.chat.type == ChatType.PRIVATE:
            await send_message(
                message,
                "This command can be only used in group not in PM",
            )
            return ""
        chat = message.chat
        chat_id = message.chat.id
        chat_name = message.chat.title

    if args:
        if args[0].lower() in ["off", "nothing", "no"]:
            settypeblacklist = "do nothing"
            sql.set_blacklist_strength(chat_id, 0, "0")
        elif args[0].lower() in ["del", "delete"]:
            settypeblacklist = "delete blacklisted message"
            sql.set_blacklist_strength(chat_id, 1, "0")
        elif args[0].lower() == "warn":
            settypeblacklist = "warn the sender"
            sql.set_blacklist_strength(chat_id, 2, "0")
        elif args[0].lower() == "mute":
            settypeblacklist = "mute the sender"
            sql.set_blacklist_strength(chat_id, 3, "0")
        elif args[0].lower() == "kick":
            settypeblacklist = "kick the sender"
            sql.set_blacklist_strength(chat_id, 4, "0")
        elif args[0].lower() == "ban":
            settypeblacklist = "ban the sender"
            sql.set_blacklist_strength(chat_id, 5, "0")
        elif args[0].lower() == "tban":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for blacklist but you didn't specified time; Try, `/blacklistmode tban <timevalue>`.

Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            restime = await extract_time(msg, args[1])
            if not restime:
                teks = """Invalid time value!
Example of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            settypeblacklist = "temporarily ban for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 6, str(args[1]))
        elif args[0].lower() == "tmute":
            if len(args) == 1:
                teks = """It looks like you tried to set time value for blacklist but you didn't specified  time; try, `/blacklistmode tmute <timevalue>`.

Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            restime = await extract_time(msg, args[1])
            if not restime:
                teks = """Invalid time value!
Examples of time value: 4m = 4 minutes, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message, teks, parse_mode=ParseMode.MARKDOWN
                )
                return ""
            settypeblacklist = "temporarily mute for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 7, str(args[1]))
        else:
            await send_message(
                message,
                "I only understand: off/del/warn/ban/kick/mute/tban/tmute!",
            )
            return ""
        if conn:
            text = "Changed blacklist mode: `{}` in *{}*!".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Changed blacklist mode: `{}`!".format(settypeblacklist)
        await send_message(message, text, parse_mode=ParseMode.MARKDOWN)
        return (
            "<b>{}:</b>\n"
            "<b>Admin:</b> {}\n"
            "Changed the blacklist mode. will {}.".format(
                html.escape(chat.title),
                mention_html(user.id, html.escape(user.first_name)),
                settypeblacklist,
            )
        )
    else:
        getmode, getvalue = sql.get_blacklist_setting(chat.id)
        if getmode == 0:
            settypeblacklist = "do nothing"
        elif getmode == 1:
            settypeblacklist = "delete"
        elif getmode == 2:
            settypeblacklist = "warn"
        elif getmode == 3:
            settypeblacklist = "mute"
        elif getmode == 4:
            settypeblacklist = "kick"
        elif getmode == 5:
            settypeblacklist = "ban"
        elif getmode == 6:
            settypeblacklist = "temporarily ban for {}".format(getvalue)
        elif getmode == 7:
            settypeblacklist = "temporarily mute for {}".format(getvalue)
        if conn:
            text = "Current blacklistmode: *{}* in *{}*.".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Current blacklistmode: *{}*.".format(settypeblacklist)
        await send_message(
            message, text, parse_mode=ParseMode.MARKDOWN
        )
    return ""


def findall(p, s):
    i = s.find(p)
    while i != -1:
        yield i
        i = s.find(p, i + 1)


@user_not_admin
async def del_blacklist(message: Message):
    chat = message.chat
    user = message.from_user
    to_match = await extract_text(message)
    if not to_match:
        return
    if is_approved(chat.id, user.id):
        return
    getmode, value = sql.get_blacklist_setting(chat.id)

    chat_filters = sql.get_chat_blacklist(chat.id)
    for trigger in chat_filters:
        pattern = r"( |^|[^\w])" + re.escape(trigger) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            try:
                if getmode == 0:
                    return
                elif getmode == 1:
                    try:
                        await message.delete()
                    except TelegramAPIError:
                        pass
                elif getmode == 2:
                    try:
                        await message.delete()
                    except TelegramAPIError:
                        pass
                    warn(
                        user,
                        chat,
                        ("Using blacklisted trigger: {}".format(trigger)),
                        message,
                        user,
                    )
                    return
                elif getmode == 3:
                    await message.delete()
                    await bot.restrict_chat_member(
                        chat.id,
                        user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                    await bot.send_message(
                        chat.id,
                        f"Muted {user.first_name} for using Blacklisted word: {trigger}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 4:
                    await message.delete()
                    # Kick == unban the current user; PTB returned a truthy
                    # result from chat.unban_member, aiogram raises instead.
                    await bot.unban_chat_member(chat.id, user.id)
                    await bot.send_message(
                        chat.id,
                        f"Kicked {user.first_name} for using Blacklisted word: {trigger}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 5:
                    await message.delete()
                    await bot.ban_chat_member(chat.id, user.id)
                    await bot.send_message(
                        chat.id,
                        f"Banned {user.first_name} for using Blacklisted word: {trigger}",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 6:
                    await message.delete()
                    bantime = await extract_time(message, value)
                    if not bantime:
                        return
                    await bot.ban_chat_member(chat.id, user.id, until_date=bantime)
                    await bot.send_message(
                        chat.id,
                        f"Banned {user.first_name} until '{value}' for using Blacklisted word: {trigger}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 7:
                    await message.delete()
                    mutetime = await extract_time(message, value)
                    if not mutetime:
                        return
                    await bot.restrict_chat_member(
                        chat.id,
                        user.id,
                        until_date=mutetime,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                    await bot.send_message(
                        chat.id,
                        f"Muted {user.first_name} until '{value}' for using Blacklisted word: {trigger}!",
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
            except TelegramAPIError as excp:
                if "message to delete not found" not in str(excp).lower():
                    LOGGER.exception("Error while deleting blacklist message.")
            break


async def __import_data__(chat_id, data, message):
    # set chat blacklist
    blacklist = data.get("blacklist", {})
    for trigger in blacklist:
        sql.add_to_blacklist(chat_id, trigger)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    blacklisted = sql.num_blacklist_chat_filters(chat_id)
    return "There are {} blacklisted words.".format(blacklisted)


def __stats__():
    return "• {} blacklist triggers, across {} chats.".format(
        sql.num_blacklist_filters(),
        sql.num_blacklist_filter_chats(),
    )


__mod_name__ = "BLACKLIST"

__help__ = """

➠ Blacklists are used to stop certain triggers from being said in a group. Any time the trigger is mentioned, the message will immediately be deleted. A good combo is sometimes to pair this up with warn filters!

➠ *NOTE*: Blacklists do not affect group admins.

» /blacklist: View the current blacklisted words.

Admin only:
» /addblacklist <triggers>: Add a trigger to the blacklist. Each line is considered one trigger, so using different lines will allow you to add multiple triggers.
» /unblacklist <triggers>: Remove triggers from the blacklist. Same newline logic applies here, so you can remove multiple triggers at once.
» /blacklistmode <off/del/warn/ban/kick/mute/tban/tmute>: Action to perform when someone sends blacklisted words.

➠ Blacklist sticker is used to stop certain stickers. Whenever a sticker is sent, the message will be deleted immediately.
➠ *NOTE:* Blacklist stickers do not affect the group admin
» /blsticker: See current blacklisted sticker
➠ *Only admin:*
» /addblsticker <sticker link>: Add the sticker trigger to the black list. Can be added via reply sticker
» /unblsticker <sticker link>: Remove triggers from blacklist. The same newline logic applies here, so you can delete multiple triggers at once
» /rmblsticker <sticker link>: Same as above
» /blstickermode <delete/ban/tban/mute/tmute>: sets up a default action on what to do if users use blacklisted stickers
Note:
» <sticker link> can be https://t.me/addstickers/<sticker> or just <sticker> or reply to the sticker message

"""
# The deleter watches every group message including commands and stickers,
# so it registers ahead of the /blacklist commands, as PTB group 11 did.
dp.message.register(
    chain(del_blacklist), GROUPS, F.text | F.command | F.sticker | F.photo
)
dp.message.register(
    chain(blacklist), *disableable("blacklist", admin_ok=True)
)
dp.message.register(chain(add_blacklist), Command("addblacklist"))
dp.message.register(chain(unblacklist), Command("unblacklist"))
dp.message.register(chain(blacklist_mode), Command("blacklistmode"))
