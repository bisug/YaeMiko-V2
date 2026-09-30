import html

from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

import Database.sql.blsticker_sql as sql
from Mikobot import LOGGER, bot, dp
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin, user_not_admin
from Mikobot.plugins.helper_funcs.misc import split_message
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.plugins.warns import warn
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html, mention_markdown


async def blackliststicker(message: Message, command: CommandObject):
    msg = message
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

    sticker_list = "<b>List blacklisted stickers currently in {}:</b>\n".format(
        chat_name,
    )

    all_stickerlist = sql.get_chat_stickers(chat_id)

    if len(args) > 0 and args[0].lower() == "copy":
        for trigger in all_stickerlist:
            sticker_list += "<code>{}</code>\n".format(html.escape(trigger))
    elif len(args) == 0:
        for trigger in all_stickerlist:
            sticker_list += " - <code>{}</code>\n".format(html.escape(trigger))

    split_text = split_message(sticker_list)
    for text in split_text:
        if sticker_list == "<b>List blacklisted stickers currently in {}:</b>\n".format(
            chat_name,
        ).format(html.escape(chat_name)):
            await send_message(
                message,
                "There are no blacklist stickers in <b>{}</b>!".format(
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )
            return
    await send_message(
        message,
        text,
        parse_mode=ParseMode.HTML,
    )


@check_admin(is_user=True)
async def add_blackliststicker(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = (msg.text or "").split(None, 1)
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
        text = words[1].replace("https://t.me/addstickers/", "")
        to_blacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )

        added = 0
        for trigger in to_blacklist:
            try:
                get = await bot.get_sticker_set(trigger)
                sql.add_to_stickers(chat_id, trigger.lower())
                added += 1
            except TelegramAPIError:
                await send_message(
                    message,
                    "Sticker `{}` can not be found!".format(trigger),
                    parse_mode=ParseMode.MARKDOWN,
                )

        if added == 0:
            return

        if len(to_blacklist) == 1:
            await send_message(
                message,
                "Sticker <code>{}</code> added to blacklist stickers in <b>{}</b>!".format(
                    html.escape(to_blacklist[0]),
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )
        else:
            await send_message(
                message,
                "<code>{}</code> stickers added to blacklist sticker in <b>{}</b>!".format(
                    added,
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )
    elif msg.reply_to_message:
        added = 0
        trigger = msg.reply_to_message.sticker.set_name
        if trigger is None:
            await send_message(
                message,
                "Sticker is invalid!",
            )
            return
        try:
            get = await bot.get_sticker_set(trigger)
            sql.add_to_stickers(chat_id, trigger.lower())
            added += 1
        except TelegramAPIError:
            await send_message(
                message,
                "Sticker `{}` can not be found!".format(trigger),
                parse_mode=ParseMode.MARKDOWN,
            )

        if added == 0:
            return

        await send_message(
            message,
            "Sticker <code>{}</code> added to blacklist stickers in <b>{}</b>!".format(
                trigger,
                html.escape(chat_name),
            ),
            parse_mode=ParseMode.HTML,
        )
    else:
        await send_message(
            message,
            "Tell me what stickers you want to add to the blacklist.",
        )


@check_admin(is_user=True)
async def unblackliststicker(message: Message, command: CommandObject):
    msg = message
    chat = message.chat
    user = message.from_user
    words = (msg.text or "").split(None, 1)
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
        text = words[1].replace("https://t.me/addstickers/", "")
        to_unblacklist = list(
            {trigger.strip() for trigger in text.split("\n") if trigger.strip()},
        )

        successful = 0
        for trigger in to_unblacklist:
            success = sql.rm_from_stickers(chat_id, trigger.lower())
            if success:
                successful += 1

        if len(to_unblacklist) == 1:
            if successful:
                await send_message(
                    message,
                    "Sticker <code>{}</code> deleted from blacklist in <b>{}</b>!".format(
                        html.escape(to_unblacklist[0]),
                        html.escape(chat_name),
                    ),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await send_message(
                    message,
                    "This sticker is not on the blacklist...!",
                )

        elif successful == len(to_unblacklist):
            await send_message(
                message,
                "Sticker <code>{}</code> deleted from blacklist in <b>{}</b>!".format(
                    successful,
                    html.escape(chat_name),
                ),
                parse_mode=ParseMode.HTML,
            )

        elif not successful:
            await send_message(
                message,
                "None of these stickers exist, so they cannot be removed.",
                parse_mode=ParseMode.HTML,
            )

        else:
            await send_message(
                message,
                "Sticker <code>{}</code> deleted from blacklist. {} did not exist, so it's not deleted.".format(
                    successful,
                    len(to_unblacklist) - successful,
                ),
                parse_mode=ParseMode.HTML,
            )
    elif msg.reply_to_message:
        trigger = msg.reply_to_message.sticker.set_name
        if trigger is None:
            await send_message(
                message,
                "Sticker is invalid!",
            )
            return
        success = sql.rm_from_stickers(chat_id, trigger.lower())

        if success:
            await send_message(
                message,
                "Sticker <code>{}</code> deleted from blacklist in <b>{}</b>!".format(
                    trigger,
                    chat_name,
                ),
                parse_mode=ParseMode.HTML,
            )
        else:
            await send_message(
                message,
                "{} not found on blacklisted stickers...!".format(trigger),
            )
    else:
        await send_message(
            message,
            "Tell me what stickers you want to add to the blacklist.",
        )


@loggable
@check_admin(is_user=True)
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
        if message.chat.type == "private":
            await send_message(
                message,
                "You can do this command in groups, not PM",
            )
            return ""
        chat = message.chat
        chat_id = message.chat.id
        chat_name = message.chat.title

    if args:
        if args[0].lower() in ["off", "nothing", "no"]:
            settypeblacklist = "turn off"
            sql.set_blacklist_strength(chat_id, 0, "0")
        elif args[0].lower() in ["del", "delete"]:
            settypeblacklist = "left, the message will be deleted"
            sql.set_blacklist_strength(chat_id, 1, "0")
        elif args[0].lower() == "warn":
            settypeblacklist = "warned"
            sql.set_blacklist_strength(chat_id, 2, "0")
        elif args[0].lower() == "mute":
            settypeblacklist = "muted"
            sql.set_blacklist_strength(chat_id, 3, "0")
        elif args[0].lower() == "kick":
            settypeblacklist = "kicked"
            sql.set_blacklist_strength(chat_id, 4, "0")
        elif args[0].lower() == "ban":
            settypeblacklist = "banned"
            sql.set_blacklist_strength(chat_id, 5, "0")
        elif args[0].lower() == "tban":
            if len(args) == 1:
                teks = """It looks like you are trying to set a temporary value to blacklist, but has not determined the time; use `/blstickermode tban <timevalue>`.
                                          Examples of time values: 4m = 4 minute, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message,
                    teks,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            settypeblacklist = "temporary banned for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 6, str(args[1]))
        elif args[0].lower() == "tmute":
            if len(args) == 1:
                teks = """It looks like you are trying to set a temporary value to blacklist, but has not determined the time; use `/blstickermode tmute <timevalue>`.
                                          Examples of time values: 4m = 4 minute, 3h = 3 hours, 6d = 6 days, 5w = 5 weeks."""
                await send_message(
                    message,
                    teks,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            settypeblacklist = "temporary muted for {}".format(args[1])
            sql.set_blacklist_strength(chat_id, 7, str(args[1]))
        else:
            await send_message(
                message,
                "I only understand off/del/warn/ban/kick/mute/tban/tmute!",
            )
            return
        if conn:
            text = "Blacklist sticker mode changed, users will be `{}` at *{}*!".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Blacklist sticker mode changed, users will be `{}`!".format(
                settypeblacklist,
            )
        await send_message(
            message,
            text,
            parse_mode=ParseMode.MARKDOWN,
        )
        return (
            "<b>{}:</b>\n"
            "<b>Admin:</b> {}\n"
            "Changed sticker blacklist mode. users will be {}.".format(
                html.escape(chat.title),
                mention_html(user.id, html.escape(user.first_name)),
                settypeblacklist,
            )
        )
    else:
        getmode, getvalue = sql.get_blacklist_setting(chat.id)
        if getmode == 0:
            settypeblacklist = "not active"
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
            settypeblacklist = "temporarily banned for {}".format(getvalue)
        elif getmode == 7:
            settypeblacklist = "temporarily muted for {}".format(getvalue)
        if conn:
            text = "Blacklist sticker mode is currently set to *{}* in *{}*.".format(
                settypeblacklist,
                chat_name,
            )
        else:
            text = "Blacklist sticker mode is currently set to *{}*.".format(
                settypeblacklist,
            )
        await send_message(
            message,
            text,
            parse_mode=ParseMode.MARKDOWN,
        )
    return ""


@user_not_admin
async def del_blackliststicker(message: Message):
    chat = message.chat
    user = message.from_user
    to_match = message.sticker
    if not to_match or not to_match.set_name:
        return
    getmode, value = sql.get_blacklist_setting(chat.id)

    chat_filters = sql.get_chat_stickers(chat.id)
    for trigger in chat_filters:
        if to_match.set_name.lower() == trigger.lower():
            try:
                if getmode == 0:
                    return
                elif getmode == 1:
                    await message.delete()
                elif getmode == 2:
                    await message.delete()
                    warn(
                        user,
                        chat,
                        "Using sticker '{}' which in blacklist stickers".format(
                            trigger,
                        ),
                        message,
                        user,
                        # conn=False,
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
                        "{} muted because using '{}' which in blacklist stickers".format(
                            mention_markdown(user.id, user.first_name),
                            trigger,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )
                    return
                elif getmode == 4:
                    await message.delete()
                    # PTB's chat.unban_member returned a truthy result; aiogram
                    # raises, so the kick has to be awaited for it to happen.
                    await bot.unban_chat_member(chat.id, user.id)
                    await bot.send_message(
                        chat.id,
                        "{} kicked because using '{}' which in blacklist stickers".format(
                            mention_markdown(user.id, user.first_name),
                            trigger,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
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
                        "{} banned because using '{}' which in blacklist stickers".format(
                            mention_markdown(user.id, user.first_name),
                            trigger,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
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
                        "{} banned for {} because using '{}' which in blacklist stickers".format(
                            mention_markdown(user.id, user.first_name),
                            value,
                            trigger,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
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
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=mutetime,
                    )
                    await bot.send_message(
                        chat.id,
                        "{} muted for {} because using '{}' which in blacklist stickers".format(
                            mention_markdown(user.id, user.first_name),
                            value,
                            trigger,
                        ),
                        parse_mode=ParseMode.MARKDOWN,
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
    blacklist = data.get("sticker_blacklist", {})
    for trigger in blacklist:
        sql.add_to_stickers(chat_id, trigger)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    blacklisted = sql.num_stickers_chat_filters(chat_id)
    return "There are `{} `blacklisted stickers.".format(blacklisted)


def __stats__():
    return "• {} blacklist stickers, across {} chats.".format(
        sql.num_stickers_filters(),
        sql.num_stickers_filter_chats(),
    )


__mod_name__ = "Stickers Blacklist"

# The deleter watches every group sticker, so it registers first.
dp.message.register(chain(del_blackliststicker), GROUPS)
dp.message.register(
    chain(blackliststicker), *disableable("blsticker", admin_ok=True)
)
dp.message.register(chain(add_blackliststicker), *disableable("addblsticker"))
dp.message.register(
    chain(unblackliststicker), Command(commands=["unblsticker", "rmblsticker"])
)
dp.message.register(chain(blacklist_mode), Command("blstickermode"))
