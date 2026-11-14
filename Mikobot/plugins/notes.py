# <============================================== IMPORTS =========================================================>
import ast
import random
import re
from io import BytesIO

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

import Database.sql.notes_sql as sql
from Mikobot import DRAGONS, LOGGER, SUPPORT_CHAT
from Mikobot import app as client
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin, connection_status
from Mikobot.plugins.helper_funcs.misc import build_keyboard, revert_buttons
from Mikobot.plugins.helper_funcs.msg_types import get_note_type
from Mikobot.plugins.helper_funcs.string_handling import (
    escape_invalid_curly_brackets,
    markdown_to_html,
)
from Mikobot.utils.consts import MessageLimit
from Mikobot.utils.parser import escape_markdown, mention_markdown

from .cust_filters import MessageHandlerChecker

# <=======================================================================================================>

FILE_MATCHER = re.compile(r"^###file_id(!photo)?###:(.*?)(?:\s|$)")
STICKER_MATCHER = re.compile(r"^###sticker(!photo)?###:")
BUTTON_MATCHER = re.compile(r"^###button(!photo)?###:(.*?)(?:\s|$)")
MYFILE_MATCHER = re.compile(r"^###file(!photo)?###:")
MYPHOTO_MATCHER = re.compile(r"^###photo(!photo)?###:")
MYAUDIO_MATCHER = re.compile(r"^###audio(!photo)?###:")
MYVOICE_MATCHER = re.compile(r"^###voice(!photo)?###:")
MYVIDEO_MATCHER = re.compile(r"^###video(!photo)?###:")
MYVIDEONOTE_MATCHER = re.compile(r"^###video_note(!photo)?###:")


# <================================================ FUNCTION =======================================================>
async def get(
    client,
    message: Message,
    notename,
    show_none=True,
    no_format=False,
    connected_chat=None,
):
    chat_id = message.chat.id
    chat = connected_chat or message.chat
    note_chat_id = message.chat.id
    note = sql.get_note(note_chat_id, notename)

    if note:
        if message.from_user and MessageHandlerChecker.check_user(message.from_user.id):
            return
        # If we're replying to a message, reply to that message (unless it's an error)
        if (
            message.reply_to_message
            and not message.reply_to_message.forum_topic_created
        ):
            reply_id = message.reply_to_message.id
        else:
            reply_id = message.id
        VALID_NOTE_FORMATTERS = [
            "first",
            "last",
            "fullname",
            "username",
            "id",
            "chatname",
            "mention",
        ]
        valid_format = escape_invalid_curly_brackets(
            note.value,
            VALID_NOTE_FORMATTERS,
        )
        if valid_format:
            if not no_format:
                if "%%%" in valid_format:
                    split = valid_format.split("%%%")
                    if all(split):
                        text = random.choice(split)
                    else:
                        text = valid_format
                else:
                    text = valid_format
            else:
                text = valid_format
            from_user = message.from_user
            first_name = (
                from_user.first_name
                if from_user
                else (message.sender_chat.title if message.sender_chat else "User")
            )
            last_name = (from_user.last_name or first_name) if from_user else first_name
            fullname = (
                " ".join([first_name, from_user.last_name])
                if from_user and from_user.last_name
                else first_name
            )
            username = (
                ("@" + from_user.username)
                if from_user and from_user.username
                else (
                    mention_markdown(from_user.id, first_name)
                    if from_user
                    else first_name
                )
            )
            mention = (
                mention_markdown(from_user.id, first_name) if from_user else first_name
            )
            chatname = (
                message.chat.title
                if message.chat.type != ChatType.PRIVATE
                else first_name
            )
            user_id = (
                from_user.id
                if from_user
                else (message.sender_chat.id if message.sender_chat else 0)
            )
            text = text.format(
                first=escape_markdown(first_name),
                last=escape_markdown(last_name),
                fullname=escape_markdown(fullname),
                username=username,
                mention=mention,
                chatname=escape_markdown(chatname),
                id=user_id,
            )
        else:
            text = ""

        keyb = []
        parseMode = ParseMode.HTML
        buttons = sql.get_buttons(note_chat_id, notename)
        if no_format:
            parseMode = None
            text += revert_buttons(buttons)
        else:
            keyb = build_keyboard(buttons)

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyb)

        try:
            reply_params = (
                ReplyParameters(message_id=reply_id) if reply_id else None
            )
            if note.msgtype in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
                await client.send_message(
                    chat_id,
                    markdown_to_html(text),
                    reply_parameters=reply_params,
                    parse_mode=parseMode,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                    reply_markup=keyboard,
                    message_thread_id=(
                        message.message_thread_id if chat.is_forum else None
                    ),
                )
            else:
                await ENUM_FUNC_MAP[note.msgtype](
                    chat_id,
                    note.file,
                    caption=markdown_to_html(text),
                    reply_parameters=reply_params,
                    parse_mode=parseMode,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                    reply_markup=keyboard,
                    message_thread_id=(
                        message.message_thread_id if chat.is_forum else None
                    ),
                )

        except RPCError as excp:
            if (
                "entity_mention_user_invalid"
                in str(getattr(excp, "message", None) or excp).lower()
            ):
                await message.reply_text(
                    "Looks like you tried to mention someone I've never seen before. If you really "
                    "want to mention them, forward one of their messages to me, and I'll be able "
                    "to tag them!",
                )
            elif FILE_MATCHER.match(note.value):
                await message.reply_text(
                    "This note was an incorrectly imported file from another bot - I can't use "
                    "it. If you really need it, you'll have to save it again. In "
                    "the meantime, I'll remove it from your notes list.",
                )
                sql.rm_note(note_chat_id, notename)
            else:
                await message.reply_text(
                    "This note could not be sent, as it is incorrectly formatted. Ask in "
                    f"@{SUPPORT_CHAT} if you can't figure out why!",
                )
                LOGGER.exception(
                    "Could not parse message #%s in chat %s",
                    notename,
                    str(note_chat_id),
                )
                LOGGER.warning("Message was: %s", str(note.value))
        return
    elif show_none:
        await message.reply_text("This note doesn't exist")


@on_message(filters.command("get"), chained=True)
@connection_status
async def cmd_get(client, message: Message):
    connected_chat = getattr(message, "connected_chat", None)
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) >= 2 and args[1].lower() == "noformat":
        await get(
            client,
            message,
            args[0].lower(),
            show_none=True,
            no_format=True,
            connected_chat=connected_chat,
        )
    elif len(args) >= 1:
        await get(
            client,
            message,
            args[0].lower(),
            show_none=True,
            connected_chat=connected_chat,
        )
    else:
        await message.reply_text("Get rekt")


@on_message(filters.regex(r"^#[^\s]+"), chained=True)
@connection_status
async def hash_get(client, msg: Message):
    connected_chat = getattr(msg, "connected_chat", None)
    fst_word = (msg.text or "").split()[0]
    no_hash = fst_word[1:].lower()
    await get(client, msg, no_hash, show_none=False, connected_chat=connected_chat)


@on_message(filters.regex(r"^/\d+$"), chained=True)
@connection_status
async def slash_get(client, msg: Message):
    connected_chat = getattr(msg, "connected_chat", None)
    text, chat_id = msg.text or "", msg.chat.id
    no_slash = text[1:]
    note_list = sql.get_all_chat_notes(chat_id)

    try:
        noteid = note_list[int(no_slash) - 1]
        note_name = str(noteid).strip(">").split()[1]
        await get(
            client, msg, note_name, show_none=False, connected_chat=connected_chat
        )
    except IndexError:
        await msg.reply_text("Wrong Note ID 😾")


@on_message(filters.command("save"), chained=True)
@connection_status
@check_admin(is_user=True)
async def save(client, msg: Message):
    chat_id = msg.chat.id
    args = msg.command[1:] if len(msg.command) > 1 else []
    if len(args) < 1:
        await msg.reply_text("You should give the note a name.")
        return

    note_name, text, data_type, content, buttons = get_note_type(msg)
    note_name = note_name.lower()
    if data_type is None:
        await msg.reply_text("Dude, there's no note content")
        return

    sql.add_note_to_db(
        chat_id,
        note_name,
        text,
        data_type,
        buttons=buttons,
        file=content,
    )

    await msg.reply_text(
        f"Yas! Added `{note_name}`.\nGet it with /get `{note_name}`, or `#{note_name}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.is_bot
        and not msg.reply_to_message.forum_topic_created
    ):
        if text:
            await msg.reply_text(
                "Seems like you're trying to save a message from a client. Unfortunately, "
                "bots can't forward bot messages, so I can't save the exact message. "
                "\nI'll save all the text I can, but if you want more, you'll have to "
                "forward the message yourself, and then save it.",
            )
        else:
            await msg.reply_text(
                "Bots are kinda handicapped by telegram, making it hard for bots to "
                "interact with other bots, so I can't save this message "
                "like I usually would - do you mind forwarding it and "
                "then saving that new message? Thanks!",
            )
        return


@on_message(filters.command("clear"), chained=True)
@connection_status
@check_admin(is_user=True)
async def clear(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []
    chat_id = message.chat.id
    if len(args) >= 1:
        notename = args[0].lower()

        if sql.rm_note(chat_id, notename):
            await message.reply_text("Successfully removed note.")
        else:
            await message.reply_text("That's not a note in my database!")


@on_message(*disableable("removeallnotes"), chained=True)
async def clearall(client, message: Message):
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
                        text="Delete all notes",
                        callback_data="notes_rmall",
                        style=ButtonStyle.DANGER,
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data="notes_cancel",
                        style=ButtonStyle.PRIMARY,
                    )
                ],
            ],
        )
        await message.reply_text(
            f"Are you sure you would like to clear ALL notes in {escape_markdown(chat.title)}? This action cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )


@on_callback(filters.regex(r"^notes_.*"), chained=True)
async def clearall_btn(client, query: CallbackQuery):
    chat = query.message.chat
    message = query.message
    member = await client.get_chat_member(chat.id, query.from_user.id)
    if query.data == "notes_rmall":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            note_list = sql.get_all_chat_notes(chat.id)
            try:
                for notename in note_list:
                    note = notename.name.lower()
                    sql.rm_note(chat.id, note)
                await message.edit_text("Deleted all notes.")
                await query.answer("Deleted all notes.")
            except RPCError:
                return

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")
    elif query.data == "notes_cancel":
        if member.status == ChatMemberStatus.OWNER or query.from_user.id in DRAGONS:
            await message.edit_text("Clearing of all notes has been cancelled.")
            await query.answer()
            return
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


@on_message(*disableable(["notes", "saved"], admin_ok=True), chained=True)
@connection_status
async def list_notes(client, message: Message):
    chat_id = message.chat.id
    note_list = sql.get_all_chat_notes(chat_id)
    notes = len(note_list) + 1
    msg = "Get note by `/notenumber` or `#notename` \n\n  *ID*    *Note* \n"
    for note_id, note in zip(range(1, notes), note_list, strict=False):
        if note_id < 10:
            note_name = f"`{note_id:2}.`  `#{(note.name.lower())}`\n"
        else:
            note_name = f"`{note_id}.`  `#{(note.name.lower())}`\n"
        if len(msg) + len(note_name) > MessageLimit.MAX_TEXT_LENGTH:
            await message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            msg = ""
        msg += note_name

    if not note_list:
        try:
            await message.reply_text("No notes in this chat!")
        except RPCError:
            await message.reply_text("No notes in this chat!")

    elif len(msg) != 0:
        await message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def __import_data__(chat_id, data, message: Message):
    failures = []
    for notename, notedata in data.get("extra", {}).items():
        match = FILE_MATCHER.match(notedata)
        matchsticker = STICKER_MATCHER.match(notedata)
        matchbtn = BUTTON_MATCHER.match(notedata)
        matchfile = MYFILE_MATCHER.match(notedata)
        matchphoto = MYPHOTO_MATCHER.match(notedata)
        matchaudio = MYAUDIO_MATCHER.match(notedata)
        matchvoice = MYVOICE_MATCHER.match(notedata)
        matchvideo = MYVIDEO_MATCHER.match(notedata)
        matchvn = MYVIDEONOTE_MATCHER.match(notedata)

        if match:
            failures.append(notename)
            notedata = notedata[match.end() :].strip()
            if notedata:
                sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)
        elif matchsticker:
            content = notedata[matchsticker.end() :].strip()
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.STICKER,
                    file=content,
                )
        elif matchbtn:
            parse = notedata[matchbtn.end() :].strip()
            notedata = parse.split("<###button###>")[0]
            buttons = parse.split("<###button###>")[1]
            buttons = ast.literal_eval(buttons)
            if buttons:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.BUTTON_TEXT,
                    buttons=buttons,
                )
        elif matchfile:
            file = notedata[matchfile.end() :].strip()
            file = file.split("<###TYPESPLIT###>")
            notedata = file[1]
            content = file[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.DOCUMENT,
                    file=content,
                )
        elif matchphoto:
            photo = notedata[matchphoto.end() :].strip()
            photo = photo.split("<###TYPESPLIT###>")
            notedata = photo[1]
            content = photo[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.PHOTO,
                    file=content,
                )
        elif matchaudio:
            audio = notedata[matchaudio.end() :].strip()
            audio = audio.split("<###TYPESPLIT###>")
            notedata = audio[1]
            content = audio[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.AUDIO,
                    file=content,
                )
        elif matchvoice:
            voice = notedata[matchvoice.end() :].strip()
            voice = voice.split("<###TYPESPLIT###>")
            notedata = voice[1]
            content = voice[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.VOICE,
                    file=content,
                )
        elif matchvideo:
            video = notedata[matchvideo.end() :].strip()
            video = video.split("<###TYPESPLIT###>")
            notedata = video[1]
            content = video[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.VIDEO,
                    file=content,
                )
        elif matchvn:
            video_note = notedata[matchvn.end() :].strip()
            video_note = video_note.split("<###TYPESPLIT###>")
            notedata = video_note[1]
            content = video_note[0]
            if content:
                sql.add_note_to_db(
                    chat_id,
                    notename[1:],
                    notedata,
                    sql.Types.VIDEO_NOTE,
                    file=content,
                )
        else:
            sql.add_note_to_db(chat_id, notename[1:], notedata, sql.Types.TEXT)

    if failures:
        with BytesIO(str.encode("\n".join(failures))) as output:
            output.name = "failed_imports.txt"
            await client.send_document(
                chat_id,
                document=output,
                file_name="failed_imports.txt",
                caption="These files/photos failed to import due to originating "
                "from another client. This is a telegram API restriction, and can't "
                "be avoided. Sorry for the inconvenience!",
                message_thread_id=(
                    message.message_thread_id if message.chat.is_forum else None
                ),
            )


# Which bot method sends each stored note type.
ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: client.send_message,
    sql.Types.BUTTON_TEXT.value: client.send_message,
    sql.Types.STICKER.value: client.send_sticker,
    sql.Types.DOCUMENT.value: client.send_document,
    sql.Types.PHOTO.value: client.send_photo,
    sql.Types.AUDIO.value: client.send_audio,
    sql.Types.VOICE.value: client.send_voice,
    sql.Types.VIDEO.value: client.send_video,
}


def __stats__():
    return f"• {sql.num_notes()} notes, across {sql.num_chats()} chats."


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    notes = sql.get_all_chat_notes(chat_id)
    return f"There are `{len(notes)}` notes in this chat."


# <=================================================== HELP ====================================================>


__help__ = """
 » /get <notename> : get the note with this notename
 » #<notename> : same as /get
 » /notes or /saved : list all saved notes in this chat
 » /number : Will pull the note of that number in the list
 ➠ If you would like to retrieve the contents of a note without any formatting, use `/get <notename> noformat`. This can \
be useful when updating a current note

*Admins only:*
 » /save <notename> <notedata> : saves notedata as a note with name notename
 ➠ A button can be added to a note by using standard markdown link syntax - the link should just be prepended with a \
`buttonurl:` section, as such: `[somelink](buttonurl:example.com)`.
 » /save <notename> : save the replied message as a note with name notename
 Separate diff replies by `%%%` to get random notes
 ➠ *Example:*
 `/save notename
 Reply 1
 %%%
 Reply 2
 %%%
 Reply 3`
 » /clear <notename>: clear note with this name
 » /removeallnotes: removes all notes from the group
 ➠ *Note:* Note names are case-insensitive, and they are automatically converted to lowercase before getting saved.

"""

__mod_name__ = "NOTES"
# <================================================ END =======================================================>
