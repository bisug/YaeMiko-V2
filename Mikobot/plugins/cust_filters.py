import asyncio
import random
import re
from html import escape

from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate
from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatMemberStatus, ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    ReplyParameters,
)

from Database.sql import cust_filters_sql as sql
from Mikobot import DEV_USERS, DRAGONS
from Mikobot import app as client
from Mikobot.events import on_callback, on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.extraction import extract_text
from Mikobot.plugins.helper_funcs.misc import build_keyboard_parser
from Mikobot.plugins.helper_funcs.msg_types import (
    Types,
    get_filter_type,
    video_note_sender,
)
from Mikobot.plugins.helper_funcs.string_handling import (
    button_markdown_parser,
    entities_map,
    escape_invalid_curly_brackets,
    markdown_to_html,
    split_quotes,
)
from Mikobot.utils.consts import ChatID
from Mikobot.utils.errors import is_reply_message_invalid
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import escape_markdown, mention_html

VALID_WELCOME_FORMATTERS = (
    "first",
    "last",
    "fullname",
    "username",
    "id",
    "chatname",
    "mention",
)

ENUM_FUNC_MAP = {
    Types.TEXT.value: client.send_message,
    Types.BUTTON_TEXT.value: client.send_message,
    Types.STICKER.value: client.send_sticker,
    Types.DOCUMENT.value: client.send_document,
    Types.PHOTO.value: client.send_photo,
    Types.AUDIO.value: client.send_audio,
    Types.VOICE.value: client.send_voice,
    Types.VIDEO.value: client.send_video,
    Types.VIDEO_NOTE.value: video_note_sender(client),
}


class AntiSpam:
    def __init__(self):
        self.whitelist = (DEV_USERS or []) + (DRAGONS or [])
        self.sec_limit = Rate(6, Duration.SECOND * 15)
        self.min_limit = Rate(20, Duration.MINUTE)
        self.hour_limit = Rate(100, Duration.HOUR)
        self.daily_limit = Rate(1000, Duration.DAY)
        self.limiter = Limiter(
            InMemoryBucket(
                [self.sec_limit, self.min_limit, self.hour_limit, self.daily_limit]
            )
        )

    def check_user(self, user):
        if user in self.whitelist:
            return False
        return not self.limiter.try_acquire(user, blocking=False)


MessageHandlerChecker = AntiSpam()


@on_message(*disableable("filters", admin_ok=True), chained=True)
@typing_action
async def list_handlers(client, message: Message):
    chat = message.chat
    user = message.from_user

    conn = await connected(client, message, chat, user.id, need_admin=False)
    if conn is not False:
        chat_id = conn
        chat_obj = await client.get_chat(conn)
        chat_name = chat_obj.title
        filter_list = f"*Filter in {escape_markdown(chat_name)}:*\n"
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            chat_name = "Local filters"
            filter_list = "*local filters:*\n"
        else:
            chat_name = chat.title
            filter_list = f"*Filters in {escape_markdown(chat_name)}*:\n"

    all_handlers = sql.get_chat_triggers(chat_id)

    if not all_handlers:
        await send_message(
            message,
            f"No filters saved in {escape_markdown(chat_name)}!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    for keyword in all_handlers:
        entry = f" • `{escape_markdown(keyword)}`\n"
        if len(entry) + len(filter_list) > 4096:
            await send_message(
                message,
                filter_list,
                parse_mode=ParseMode.MARKDOWN,
            )
            filter_list = entry
        else:
            filter_list += entry

    await send_message(
        message,
        filter_list,
        parse_mode=ParseMode.MARKDOWN,
    )


@on_message(filters.command("filter"), chained=True)
@typing_action
@check_admin(is_user=True)
async def filter_cmd(client, message: Message):
    chat = message.chat
    user = message.from_user
    msg = message
    args = msg.text.split(None, 1)

    buttons = None
    conn = await connected(client, message, chat, user.id)
    if conn is not False:
        chat_id = conn
        chat_obj = await client.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            chat_name = "local filters"
        else:
            chat_name = chat.title

    if not msg.reply_to_message and len(args) < 2:
        await send_message(
            message,
            "Provide a keyword for the filter's reply keyboard.",
        )
        return

    if msg.reply_to_message and not msg.reply_to_message.forum_topic_created:
        if len(args) < 2:
            await send_message(
                message,
                "Provide a keyword for this filter's reply.",
            )
            return
        else:
            keyword = args[1]
    else:
        extracted = split_quotes(args[1])
        if len(extracted) < 1:
            return
        keyword = extracted[0].lower()

    text, file_type, file_id, media_spoiler = get_filter_type(msg)
    if not msg.reply_to_message and len(extracted) >= 2:
        offset = len(extracted[1]) - len(msg.text)
        text, buttons = button_markdown_parser(
            extracted[1],
            entities=entities_map(msg),
            offset=offset,
        )
        text = text.strip()
        if not text:
            await send_message(
                message,
                "A filter needs a message. Buttons alone are not enough.",
            )
            return

    if len(args) >= 2:
        if msg.reply_to_message:
            if msg.reply_to_message.forum_topic_created:
                offset = len(extracted[1]) - len(msg.text)

                text, buttons = button_markdown_parser(
                    extracted[1], entities=entities_map(msg), offset=offset
                )

                text = text.strip()
                if not text:
                    await send_message(
                        message,
                        "A filter needs a message. Buttons alone are not enough.",
                    )
                    return
            else:
                pass

    elif msg.reply_to_message and len(args) >= 1:
        if msg.reply_to_message.text:
            text_to_parsing = msg.reply_to_message.text
        elif msg.reply_to_message.caption:
            text_to_parsing = msg.reply_to_message.caption
        else:
            text_to_parsing = ""
        offset = len(text_to_parsing)
        text, buttons = button_markdown_parser(
            text_to_parsing,
            entities=entities_map(msg),
            offset=offset,
        )
        text = text.strip()

    elif not text and not file_type:
        await send_message(
            message,
            "Provide a keyword for this filter's reply.",
        )
        return

    elif msg.reply_to_message:
        if msg.reply_to_message.forum_topic_created:
            return

        if msg.reply_to_message.text:
            text_to_parsing = msg.reply_to_message.text
        elif msg.reply_to_message.caption:
            text_to_parsing = msg.reply_to_message.caption
        else:
            text_to_parsing = ""
        offset = len(text_to_parsing)
        text, buttons = button_markdown_parser(
            text_to_parsing,
            entities=entities_map(msg),
            offset=offset,
        )
        text = text.strip()
        if (msg.reply_to_message.text or msg.reply_to_message.caption) and not text:
            await send_message(
                message,
                "A filter needs a message. Buttons alone are not enough.",
            )
            return

    else:
        await send_message(message, "Invalid filter.")
        return

    add = await addnew_filter(
        message, chat_id, keyword, text, file_type, file_id, buttons, media_spoiler
    )

    if add is True:
        await send_message(
            message,
            "Saved filter '{}' in *{}*!".format(keyword, chat_name),
            parse_mode=ParseMode.MARKDOWN,
        )


@on_message(filters.command("stop"), chained=True)
@typing_action
@check_admin(is_user=True)
async def stop_filter(client, message: Message):
    chat = message.chat
    user = message.from_user
    args = (message.text or message.caption or "").split(None, 1)

    conn = await connected(client, message, chat, user.id)
    if conn is not False:
        chat_id = conn
        chat_obj = await client.get_chat(conn)
        chat_name = chat_obj.title
    else:
        chat_id = message.chat.id
        if chat.type == ChatType.PRIVATE:
            chat_name = "Local filters"
        else:
            chat_name = chat.title

    if len(args) < 2:
        await send_message(message, "Specify the filter to stop.")
        return

    chat_filters = sql.get_chat_triggers(chat_id)

    if not chat_filters:
        await send_message(message, "No filters are active here.")
        return

    for keyword in chat_filters:
        if keyword == args[1]:
            sql.remove_filter(chat_id, args[1])
            await send_message(
                message,
                "Okay, I'll stop replying to that filter in *{}*.".format(chat_name),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    await send_message(
        message,
        "That is not a filter. Use /filters to see active filters.",
    )


@on_message(filters.text, chained=True)
async def reply_filter(client, message: Message):
    chat = message.chat

    if not message.from_user or message.from_user.id == ChatID.SERVICE_CHAT:
        return
    to_match = await extract_text(message)
    if not to_match:
        return

    chat_filters = sql.get_chat_triggers(chat.id)
    for keyword in chat_filters:
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            if MessageHandlerChecker.check_user(message.from_user.id):
                return
            filt = await asyncio.to_thread(sql.get_filter, chat.id, keyword)
            if filt.reply_text is not None:
                buttons = await asyncio.to_thread(
                    sql.get_buttons, chat.id, filt.keyword
                )
                keyb = build_keyboard_parser(chat.id, buttons)
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyb)

                if filt.reply_text:
                    if "%%%" in filt.reply_text:
                        split = filt.reply_text.split("%%%")
                        if all(split):
                            text = random.choice(split)
                        else:
                            text = filt.reply_text
                    else:
                        text = filt.reply_text
                    if text.startswith("~!") and text.endswith("!~"):
                        sticker_id = text.replace("~!", "").replace("!~", "")
                        try:
                            await client.send_sticker(
                                chat.id,
                                sticker_id,
                                reply_parameters=ReplyParameters(message_id=message.id),
                                message_thread_id=(
                                    message.message_thread_id if chat.is_forum else None
                                ),
                            )
                            return
                        except RPCError as excp:
                            if (
                                excp.message
                                == "Wrong remote file identifier specified: wrong padding in the string"
                            ):
                                await client.send_message(
                                    chat.id,
                                    "Could not send the message. Check the sticker ID.",
                                    message_thread_id=(
                                        message.message_thread_id
                                        if chat.is_forum
                                        else None
                                    ),
                                )
                                return
                            else:
                                LOGGER.exception("Error in filters: " + excp.message)
                                return
                    valid_format = escape_invalid_curly_brackets(
                        text,
                        VALID_WELCOME_FORMATTERS,
                    )
                    if valid_format:
                        filtext = valid_format.format(
                            first=escape(message.from_user.first_name),
                            last=escape(
                                message.from_user.last_name
                                or message.from_user.first_name,
                            ),
                            fullname=" ".join(
                                (
                                    [
                                        escape(message.from_user.first_name),
                                        escape(message.from_user.last_name),
                                    ]
                                    if message.from_user.last_name
                                    else [escape(message.from_user.first_name)]
                                ),
                            ),
                            username=(
                                "@" + escape(message.from_user.username)
                                if message.from_user.username
                                else mention_html(
                                    message.from_user.id,
                                    message.from_user.first_name,
                                )
                            ),
                            mention=mention_html(
                                message.from_user.id,
                                message.from_user.first_name,
                            ),
                            chatname=(
                                escape(message.chat.title)
                                if message.chat.type != ChatType.PRIVATE
                                else escape(message.from_user.first_name)
                            ),
                            id=message.from_user.id,
                        )
                    else:
                        filtext = ""
                else:
                    filtext = ""

                if filt.file_type in (Types.BUTTON_TEXT, Types.TEXT):
                    try:
                        await message.reply_text(
                            markdown_to_html(filtext),
                            parse_mode=ParseMode.HTML,
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                            reply_markup=keyboard,
                        )
                    except RPCError as excp:
                        LOGGER.exception("Error in filters: " + excp.message)
                        try:
                            await send_message(
                                message,
                                get_exception(excp, filt, chat),
                            )
                        except RPCError as excp:
                            LOGGER.exception(
                                "Failed to send message: " + excp.message,
                            )
                else:
                    try:
                        if filt.file_type not in [
                            Types.PHOTO.value,
                            Types.VIDEO,
                        ]:
                            await ENUM_FUNC_MAP[filt.file_type](
                                chat.id,
                                filt.file_id,
                                reply_markup=keyboard,
                                reply_parameters=ReplyParameters(message_id=message.id),
                                message_thread_id=(
                                    message.message_thread_id if chat.is_forum else None
                                ),
                            )
                        else:
                            await ENUM_FUNC_MAP[filt.file_type](
                                chat.id,
                                filt.file_id,
                                reply_markup=keyboard,
                                caption=filt.reply_text,
                                reply_parameters=ReplyParameters(message_id=message.id),
                                message_thread_id=(
                                    message.message_thread_id if chat.is_forum else None
                                ),
                                has_spoiler=message.has_media_spoiler,
                            )
                    except RPCError:
                        await send_message(
                            message,
                            "I cannot send the filter's content here.",
                        )
                break
            else:
                if filt.is_sticker:
                    await message.reply_sticker(filt.reply)
                elif filt.is_document:
                    await message.reply_document(filt.reply)
                elif filt.is_image:
                    await message.reply_photo(
                        filt.reply, has_spoiler=filt.has_media_spoiler
                    )
                elif filt.is_audio:
                    await message.reply_audio(filt.reply)
                elif filt.is_voice:
                    await message.reply_voice(filt.reply)
                elif filt.is_video:
                    await message.reply_video(
                        filt.reply, has_spoiler=filt.has_media_spoiler
                    )
                elif filt.has_buttons:
                    buttons = sql.get_buttons(chat.id, filt.keyword)
                    keyb = build_keyboard_parser(chat.id, buttons)
                    keyboard = InlineKeyboardMarkup(inline_keyboard=keyb)

                    try:
                        await client.send_message(
                            chat.id,
                            markdown_to_html(filt.reply),
                            parse_mode=ParseMode.HTML,
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                            reply_markup=keyboard,
                            message_thread_id=(
                                message.message_thread_id if chat.is_forum else None
                            ),
                        )
                    except RPCError as excp:
                        if (
                            "unsupported url protocol"
                            in str(excp.message or excp).lower()
                        ):
                            try:
                                await send_message(
                                    message,
                                    "You seem to be trying to use an unsupported URL protocol. "
                                    "Telegram doesn't support buttons for some protocols, such as tg://. Please try "
                                    "again...",
                                )
                            except RPCError as excp:
                                LOGGER.exception("Error in filters: " + excp.message)
                        else:
                            try:
                                await send_message(
                                    message,
                                    "Could not send the message. Its formatting is invalid.",
                                )
                            except RPCError as excp:
                                LOGGER.exception("Error in filters: " + excp.message)
                            LOGGER.warning(
                                "Message %s could not be parsed",
                                str(filt.reply),
                            )
                            LOGGER.exception(
                                "Could not parse filter %s in chat %s",
                                str(filt.keyword),
                                str(chat.id),
                            )

                else:
                    try:
                        await client.send_message(
                            chat.id,
                            filt.reply,
                            message_thread_id=(
                                message.message_thread_id if chat.is_forum else None
                            ),
                        )
                    except RPCError as excp:
                        LOGGER.exception("Error in filters: " + excp.message)
                break


@on_message(GROUPS & filters.command("removeallfilters"), chained=True)
async def rmall_filters(client, message: Message):
    chat = message.chat
    user = message.from_user
    member = await client.get_chat_member(chat.id, user.id)
    if member.status != ChatMemberStatus.OWNER and user.id not in DRAGONS:
        await message.reply_text(
            "Only the chat owner can clear all filters at once.",
        )
    else:
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="STOP ALL FILTERS",
                        callback_data="filters_rmall",
                        style=ButtonStyle.DANGER,
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="CANCEL",
                        callback_data="filters_cancel",
                        style=ButtonStyle.DEFAULT,
                    )
                ],
            ],
        )
        await message.reply_text(
            f"Stop all filters in {escape_markdown(chat.title)}? This cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )


@on_callback(filters.regex(r"^filters_.*"), chained=True)
async def rmall_callback(client, query: CallbackQuery):
    chat = query.message.chat
    msg = query.message
    member = await client.get_chat_member(chat.id, query.from_user.id)
    if query.data == "filters_rmall":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            allfilters = sql.get_chat_triggers(chat.id)
            if not allfilters:
                await msg.edit_text("There are no filters to stop.")
                await query.answer("There are no filters to remove.")
                return

            for i in allfilters:
                sql.remove_filter(chat.id, i)

            await msg.edit_text(
                f"Removed {len(allfilters)} filters in {escape(chat.title)}"
            )
            await query.answer("All filters removed.")

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")
    elif query.data == "filters_cancel":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            await msg.edit_text("Filter removal cancelled.")
            await query.answer()
            return
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


def get_exception(excp, filt, chat):
    err_str = str(excp).lower()
    if "button_url_invalid" in err_str or "url_invalid" in err_str:
        return "You seem to be trying to use an unsupported URL protocol. Telegram does not support buttons for some protocols, such as tg://. Please try again!"
    elif is_reply_message_invalid(excp):
        return "noreply"
    else:
        LOGGER.warning("Message %s could not be parsed", str(filt.reply))
        LOGGER.exception(
            "Could not parse filter %s in chat %s",
            str(filt.keyword),
            str(chat.id),
        )
        return "This data could not be sent because it is incorrectly formatted."


async def addnew_filter(
    message, chat_id, keyword, text, file_type, file_id, buttons, has_spoiler
):
    msg = message
    totalfilt = sql.get_chat_triggers(chat_id)
    if len(totalfilt) >= 150:
        await msg.reply_text("This group has reached the limit of 150 filters.")
        return False
    else:
        sql.new_add_filter(
            chat_id, keyword, text, file_type, file_id, buttons, has_spoiler
        )
        return True


def __stats__():
    return "• {} filters, across {} chats.".format(sql.num_filters(), sql.num_chats())


async def __import_data__(chat_id, data, message):
    filters_data = data.get("filters", {})
    for trigger in filters_data:
        sql.add_to_blacklist(chat_id, trigger)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    cust_filters = sql.get_chat_triggers(chat_id)
    return "There are `{}` custom filters here.".format(len(cust_filters))


__help__ = """
Commands:
/filters: List active filters in this chat.

Admin only:
/filter <keyword> <reply message>: Add a filter. When the keyword is mentioned, the bot replies with the given message. Replying to a sticker with a keyword makes the bot reply with that sticker. Keywords are lowercase. Use quotes for a multi-word keyword, for example /filter "hey there" How you doin?

Separate replies with %%% to get random replies. Example:
/filter "filtername"
 Reply 1
 %%%
 Reply 2
 %%%
 Reply 3

/stop <filter keyword>: Stop a filter.

Chat creator only:
/removeallfilters: Remove all filters in this chat at once.

Filters support formatters such as {first} and {last}, and buttons. Media spoilers and media captions are supported.
"""

__mod_name__ = "Filters"
