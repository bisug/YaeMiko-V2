# <============================================== IMPORTS =========================================================>
import ast
import random
import re
from io import BytesIO

from aiogram import F
from aiogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

import Database.sql.notes_sql as sql
from Mikobot import DRAGONS, LOGGER, MESSAGE_DUMP, SUPPORT_CHAT, bot, dp
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin, connection_status
from Mikobot.plugins.helper_funcs.misc import build_keyboard, revert_buttons
from Mikobot.plugins.helper_funcs.msg_types import get_note_type
from Mikobot.plugins.helper_funcs.string_handling import (
    escape_invalid_curly_brackets,
    markdown_to_html,
)
from Mikobot.utils.consts import MessageLimit
from Mikobot.utils.gate import chain
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
        if MessageHandlerChecker.check_user(message.from_user.id):
            return
        # If we're replying to a message, reply to that message (unless it's an error)
        if (
            message.reply_to_message
            and not message.reply_to_message.forum_topic_created
        ):
            reply_id = message.reply_to_message.message_id
        else:
            reply_id = message.message_id
        if note.is_reply:
            if MESSAGE_DUMP:
                try:
                    await bot.forward_message(
                        chat_id=chat_id,
                        from_chat_id=MESSAGE_DUMP,
                        message_id=note.value,
                    )
                except TelegramAPIError as excp:
                    if "message to forward not found" in str(excp.message or excp).lower():
                        await message.answer(
                            "This message seems to have been lost - I'll remove it "
                            "from your notes list.",
                        )
                        sql.rm_note(note_chat_id, notename)
                    else:
                        raise
            else:
                try:
                    await bot.forward_message(
                        chat_id=chat_id,
                        from_chat_id=chat_id,
                        message_id=markdown_to_html(note.value),
                    )
                except TelegramAPIError as excp:
                    if "message to forward not found" in str(excp.message or excp).lower():
                        await message.answer(
                            "Looks like the original sender of this note has deleted "
                            "their message - sorry! Get your bot admin to start using a "
                            "message dump to avoid this. I'll remove this note from "
                            "your saved notes.",
                        )
                        sql.rm_note(note_chat_id, notename)
                    else:
                        raise
        else:
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
                text = text.format(
                    first=escape_markdown(message.from_user.first_name),
                    last=escape_markdown(
                        message.from_user.last_name or message.from_user.first_name,
                    ),
                    fullname=escape_markdown(
                        " ".join(
                            (
                                [
                                    message.from_user.first_name,
                                    message.from_user.last_name,
                                ]
                                if message.from_user.last_name
                                else [message.from_user.first_name]
                            ),
                        ),
                    ),
                    username=(
                        "@" + message.from_user.username
                        if message.from_user.username
                        else mention_markdown(
                            message.from_user.id,
                            message.from_user.first_name,
                        )
                    ),
                    mention=mention_markdown(
                        message.from_user.id,
                        message.from_user.first_name,
                    ),
                    chatname=escape_markdown(
                        (
                            message.chat.title
                            if message.chat.type != "private"
                            else message.from_user.first_name
                        ),
                    ),
                    id=message.from_user.id,
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
                if note.msgtype in (sql.Types.BUTTON_TEXT, sql.Types.TEXT):
                    await bot.send_message(
                        chat_id,
                        markdown_to_html(text),
                        reply_to_message_id=reply_id,
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
                        reply_to_message_id=reply_id,
                        parse_mode=parseMode,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                        reply_markup=keyboard,
                        message_thread_id=(
                            message.message_thread_id if chat.is_forum else None
                        ),
                    )

            except TelegramAPIError as excp:
                if excp.message == "Entity_mention_user_invalid":
                    await message.answer(
                        "Looks like you tried to mention someone I've never seen before. If you really "
                        "want to mention them, forward one of their messages to me, and I'll be able "
                        "to tag them!",
                    )
                elif FILE_MATCHER.match(note.value):
                    await message.answer(
                        "This note was an incorrectly imported file from another bot - I can't use "
                        "it. If you really need it, you'll have to save it again. In "
                        "the meantime, I'll remove it from your notes list.",
                    )
                    sql.rm_note(note_chat_id, notename)
                else:
                    await message.answer(
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
        await message.answer("This note doesn't exist")


@connection_status
async def cmd_get(message: Message, command: CommandObject, connected_chat=None):
    args = command.args.split() if command.args else []
    if len(args) >= 2 and args[1].lower() == "noformat":
        await get(message, args[0].lower(), show_none=True, no_format=True, connected_chat=connected_chat)
    elif len(args) >= 1:
        await get(message, args[0].lower(), show_none=True, connected_chat=connected_chat)
    else:
        await message.answer("Get rekt")


@connection_status
async def hash_get(msg: Message, connected_chat=None):
    fst_word = (msg.text or "").split()[0]
    no_hash = fst_word[1:].lower()
    await get(msg, no_hash, show_none=False, connected_chat=connected_chat)


@connection_status
async def slash_get(msg: Message, connected_chat=None):
    text, chat_id = msg.text or "", msg.chat.id
    no_slash = text[1:]
    note_list = sql.get_all_chat_notes(chat_id)

    try:
        noteid = note_list[int(no_slash) - 1]
        note_name = str(noteid).strip(">").split()[1]
        await get(msg, note_name, show_none=False, connected_chat=connected_chat)
    except IndexError:
        await msg.answer("Wrong Note ID 😾")


@connection_status
@check_admin(is_user=True)
async def save(msg: Message, command: CommandObject):
    chat_id = msg.chat.id
    if len(command.args.split() if command.args else []) < 1:
        await msg.answer("You should give the note a name.")
        return

    note_name, text, data_type, content, buttons = get_note_type(msg)
    note_name = note_name.lower()
    if data_type is None:
        await msg.answer("Dude, there's no note content")
        return

    sql.add_note_to_db(
        chat_id,
        note_name,
        text,
        data_type,
        buttons=buttons,
        file=content,
    )

    await msg.answer(
        f"Yas! Added `{note_name}`.\nGet it with /get `{note_name}`, or `#{note_name}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user.is_bot
        and not msg.reply_to_message.forum_topic_created
    ):
        if text:
            await msg.answer(
                "Seems like you're trying to save a message from a bot. Unfortunately, "
                "bots can't forward bot messages, so I can't save the exact message. "
                "\nI'll save all the text I can, but if you want more, you'll have to "
                "forward the message yourself, and then save it.",
            )
        else:
            await msg.answer(
                "Bots are kinda handicapped by telegram, making it hard for bots to "
                "interact with other bots, so I can't save this message "
                "like I usually would - do you mind forwarding it and "
                "then saving that new message? Thanks!",
            )
        return


@connection_status
@check_admin(is_user=True)
async def clear(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    chat_id = message.chat.id
    if len(args) >= 1:
        notename = args[0].lower()

        if sql.rm_note(chat_id, notename):
            await message.reply("Successfully removed note.")
        else:
            await message.reply(
                "That's not a note in my database!"
            )


async def clearall(message: Message):
    chat = message.chat
    user = message.from_user
    member = await bot.get_chat_member(chat.id, user.id)
    if member.status != ChatMemberStatus.CREATOR and user.id not in DRAGONS:
        await message.reply(
            "Only the chat owner can clear all notes at once.",
        )
    else:
        buttons = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Delete all notes",
                        callback_data="notes_rmall",
                     style=ButtonStyle.DANGER),
                ],
                [InlineKeyboardButton(text="Cancel", callback_data="notes_cancel", style=ButtonStyle.PRIMARY)],
            ],
        )
        await message.reply(
            f"Are you sure you would like to clear ALL notes in {escape_markdown(chat.title)}? This action cannot be undone.",
            reply_markup=buttons,
            parse_mode=ParseMode.MARKDOWN,
        )


async def clearall_btn(query: CallbackQuery):
    chat = query.message.chat
    message = query.message
    member = await bot.get_chat_member(chat.id, query.from_user.id)
    if query.data == "notes_rmall":
        if member.status == ChatMemberStatus.CREATOR or query.from_user.id in DRAGONS:
            note_list = sql.get_all_chat_notes(chat.id)
            try:
                for notename in note_list:
                    note = notename.name.lower()
                    sql.rm_note(chat.id, note)
                await message.edit_text("Deleted all notes.")
                await query.answer("Deleted all notes.")
            except TelegramAPIError:
                return

        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")

        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")
    elif query.data == "notes_cancel":
        if member.status == ChatMemberStatus.CREATOR or query.from_user.id in DRAGONS:
            await message.edit_text("Clearing of all notes has been cancelled.")
            await query.answer()
            return
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            await query.answer("Only owner of the chat can do this.")
        if member.status == ChatMemberStatus.MEMBER:
            await query.answer("You need to be admin to do this.")


@connection_status
async def list_notes(message: Message):
    chat_id = message.chat.id
    note_list = sql.get_all_chat_notes(chat_id)
    notes = len(note_list) + 1
    msg = "Get note by `/notenumber` or `#notename` \n\n  *ID*    *Note* \n"
    for note_id, note in zip(range(1, notes), note_list):
        if note_id < 10:
            note_name = f"`{note_id:2}.`  `#{(note.name.lower())}`\n"
        else:
            note_name = f"`{note_id}.`  `#{(note.name.lower())}`\n"
        if len(msg) + len(note_name) > MessageLimit.MAX_TEXT_LENGTH:
            await message.reply(
                msg, parse_mode=ParseMode.MARKDOWN
            )
            msg = ""
        msg += note_name

    if not note_list:
        try:
            await message.reply("No notes in this chat!")
        except TelegramAPIError:
            await message.reply(
                "No notes in this chat!"
            )

    elif len(msg) != 0:
        await message.reply(msg, parse_mode=ParseMode.MARKDOWN)


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
            await bot.send_document(
                chat_id,
                document=output,
                filename="failed_imports.txt",
                caption="These files/photos failed to import due to originating "
                "from another bot. This is a telegram API restriction, and can't "
                "be avoided. Sorry for the inconvenience!",
                message_thread_id=(
                    message.message_thread_id if message.chat.is_forum else None
                ),
            )


# Which bot method sends each stored note type.
ENUM_FUNC_MAP = {
    sql.Types.TEXT.value: bot.send_message,
    sql.Types.BUTTON_TEXT.value: bot.send_message,
    sql.Types.STICKER.value: bot.send_sticker,
    sql.Types.DOCUMENT.value: bot.send_document,
    sql.Types.PHOTO.value: bot.send_photo,
    sql.Types.AUDIO.value: bot.send_audio,
    sql.Types.VOICE.value: bot.send_voice,
    sql.Types.VIDEO.value: bot.send_video,
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

# <================================================ HANDLER =======================================================>
# #notename and /<number> are registered before /get so a note reply wins
# over the command path, as PTB's registration order did.
dp.message.register(chain(cmd_get), Command("get"))
# connected_chat is injected by the connection_status gate in chat_status.py;
# aiogram fills a declared parameter only when the gate supplied it, so the
# None default is the unconnected case.
dp.message.register(chain(hash_get), F.text.regexp(r"^#[^\s]+"))
dp.message.register(chain(slash_get), F.text.regexp(r"^/\d+$"))
dp.message.register(chain(save), Command("save"))
dp.message.register(chain(clear), Command("clear"))
dp.message.register(chain(list_notes), *disableable(["notes", "saved"], admin_ok=True))
dp.message.register(chain(clearall), *disableable("removeallnotes"))
dp.callback_query.register(chain(clearall_btn), F.data.regexp(r"^notes_.*"))
# <================================================ END =======================================================>
