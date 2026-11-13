# <============================================== IMPORTS =========================================================>
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
)

from Database.sql import cust_filters_sql as sql
from Mikobot import DEV_USERS, DRAGONS, LOGGER
from Mikobot import app as client
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.connection import connected
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.alternate import send_message, typing_action
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.extraction import extract_text
from Mikobot.plugins.helper_funcs.misc import build_keyboard_parser
from Mikobot.plugins.helper_funcs.msg_types import Types, get_filter_type
from Mikobot.plugins.helper_funcs.string_handling import (
    button_markdown_parser,
    entities_map,
    escape_invalid_curly_brackets,
    markdown_to_html,
    split_quotes,
)
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import escape_markdown, mention_html

# <=======================================================================================================>

ENUM_FUNC_MAP = {
    Types.TEXT.value: client.send_message,
    Types.BUTTON_TEXT.value: client.send_message,
    Types.STICKER.value: client.send_sticker,
    Types.DOCUMENT.value: client.send_document,
    Types.PHOTO.value: client.send_photo,
    Types.AUDIO.value: client.send_audio,
    Types.VOICE.value: client.send_voice,
    Types.VIDEO.value: client.send_video,
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


# <================================================ FUNCTION =======================================================>
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
            f"No filters saving in {escape_markdown(chat_name)}!",
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
            "Please provide keyboard keyword for this filter to reply with!",
        )
        return

    if msg.reply_to_message and not msg.reply_to_message.forum_topic_created:
        if len(args) < 2:
            await send_message(
                message,
                "Please provide keyword for this filter to reply with!",
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
                "There is no note message - You can't JUST have buttons, you need a message to go with it!",
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
                        "There is no note message - You can't JUST have buttons, you need a message to go with it!",
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
            "Please provide keyword for this filter reply with!",
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
                "There is no note message - You can't JUST have buttons, you need a message to go with it!",
            )
            return

    else:
        await send_message(message, "Invalid filter!")
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
        await send_message(message, "What should i stop?")
        return

    chat_filters = sql.get_chat_triggers(chat_id)

    if not chat_filters:
        await send_message(message, "No filters active here!")
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
        "That's not a filter - Click: /filters to get currently active filters.",
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
            filt = sql.get_filter(chat.id, keyword)
            if filt.reply_text is not None:
                buttons = sql.get_buttons(chat.id, filt.keyword)
                keyb = build_keyboard_parser(chat.id, buttons)
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyb)

                VALID_WELCOME_FORMATTERS = [
                    "first",
                    "last",
                    "fullname",
                    "username",
                    "id",
                    "chatname",
                    "mention",
                ]
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
                                reply_to_message_id=message.id,
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
                                    "Message couldn't be sent, Is the sticker id valid?",
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
                                reply_to_message_id=message.id,
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
                                reply_to_message_id=message.id,
                                message_thread_id=(
                                    message.message_thread_id if chat.is_forum else None
                                ),
                                has_spoiler=message.has_media_spoiler,
                            )
                    except RPCError:
                        await send_message(
                            message,
                            "I don't have the permission to send the content of the filter.",
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
                                    "You seem to be trying to use an unsupported url protocol. "
                                    "Telegram doesn't support buttons for some protocols, such as tg://. Please try "
                                    "again...",
                                )
                            except RPCError as excp:
                                LOGGER.exception("Error in filters: " + excp.message)
                        else:
                            try:
                                await send_message(
                                    message,
                                    "This message couldn't be sent as it's incorrectly formatted.",
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
            "Only the chat owner can clear all notes at once.",
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
                        style=ButtonStyle.PRIMARY,
                    )
                ],
            ],
        )
        await message.reply_text(
            f"Are you sure you would like to stop ALL filters in {escape_markdown(chat.title)}? This action cannot be undone.",
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
                await msg.edit_text("No filters in this chat, nothing to stop!")
                await query.answer("There are no filters to remove.")
                return

            count = 0
            filterlist = []
            for x in allfilters:
                count += 1
                filterlist.append(x)

            for i in filterlist:
                sql.remove_filter(chat.id, i)

            await msg.edit_text(f"Cleaned {count} filters in {escape(chat.title)}")
            await query.answer("All filters removed.")

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")
    elif query.data == "filters_cancel":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            await msg.edit_text("Clearing of all filters has been cancelled.")
            await query.answer()
            return
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


def get_exception(excp, filt, chat):
    if "unsupported url protocol" in str(excp.message or excp).lower():
        return "You seem to be trying to use the URL protocol which is not supported. Telegram does not support key for multiple protocols, such as tg: //. Please try again!"
    elif "reply message not found" in str(excp.message or excp).lower():
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
        await msg.reply_text("This group has reached its max filters limit of 150.")
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


# <=================================================== HELP ====================================================>


__help__ = """
» `/filters`*:* List all active filters saved in the chat.

➠ *Admin only:*

» `/filter <keyword> <reply message>`*:* Add a filter to this chat. The bot will now reply that message whenever 'keyword'\
is mentioned. If you reply to a sticker with a keyword, the bot will reply with that sticker. NOTE: all filter \
keywords are in lowercase. If you want your keyword to be a sentence, use quotes. eg: /filter "hey there" How you \
doin?

➠ Separate diff replies by `%%%` to get random replies
➠ *Example:*

» `/filter "filtername"
 Reply 1
 %%%
 Reply 2
 %%%
 Reply 3`

» `/stop <filter keyword>`*:* Stop that filter.

➠ *Chat creator only:*
» `/removeallfilters`*:* Remove all chat filters at once.

➠ *Note*: Filters also support markdown formatters like: {first}, {last} etc.. and buttons.
➠ Now Supports media spoilers too, and media caption.
"""

__mod_name__ = "FILTERS"
