import os
import tempfile
import uuid
from html import escape
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext, CommandHandler

from Mikobot import dispatcher
from Mikobot.state import state
from telegram.constants import KeyboardButtonStyle

ENDPOINT = "https://sasta-api.vercel.app/googleImageSearch"


class STRINGS:
    REQUESTING_API_SERVER = "🫧"
    DOWNLOADING_MEDIA = "🔍"
    UPLOADING_TO_API_SERVER = "📤"
    PARSING_RESULT = "📥"
    RESULT = "Query: {query}\nGoogle Page: <a href=\"{search_url}\">Link</a>"
    OPEN_SEARCH_PAGE = "OPEN LINK"


def _valid_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def reverse_image_search(update: Update, context: CallbackContext):
    message = update.message
    args = message.text.split(None, 1)
    if len(args) > 1:
        image_url = args[1]
        if not _valid_url(image_url):
            await message.reply_text("Please provide a valid HTTP(S) image URL.")
            return
        status_msg = await message.reply_text(STRINGS.REQUESTING_API_SERVER)
        try:
            response = await state.get(
                ENDPOINT, params={"image_url": image_url}, timeout=20
            )
        except Exception:
            await status_msg.edit_text("The reverse image service is unavailable.")
            return
    elif message.reply_to_message and any(
        getattr(message.reply_to_message, name, None)
        for name in ("photo", "sticker", "document")
    ):
        reply = message.reply_to_message
        status_msg = await message.reply_text(STRINGS.DOWNLOADING_MEDIA)
        with tempfile.TemporaryDirectory(prefix="yae-reverse-") as temp_dir:
            file_path = os.path.join(temp_dir, uuid.uuid4().hex)
            try:
                file_id = (
                    reply.photo[-1].file_id
                    if reply.photo
                    else reply.sticker.file_id
                    if reply.sticker
                    else reply.document.file_id
                )
                file = await context.bot.get_file(file_id)
                await file.download_to_drive(file_path)
                await status_msg.edit_text(STRINGS.UPLOADING_TO_API_SERVER)
                with open(file_path, "rb") as image_file:
                    response = await state.post(
                        ENDPOINT, files={"file": image_file}, timeout=20
                    )
            except Exception:
                await status_msg.edit_text("The image could not be processed.")
                return
    else:
        await message.reply_text("Reply to an image or provide an image URL.")
        return

    try:
        response.raise_for_status()
        payload = response.json()
        query = payload.get("query", "")
        search_url = payload.get("search_url")
        if not _valid_url(search_url):
            raise ValueError("invalid search URL")
    except Exception:
        await status_msg.edit_text("The reverse image service returned an invalid response.")
        return

    text = STRINGS.RESULT.format(
        query=f"<code>{escape(query)}</code>" if query else "<i>Name not found</i>",
        search_url=search_url,
    )
    await message.reply_text(
        text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(STRINGS.OPEN_SEARCH_PAGE, url=search_url, style=KeyboardButtonStyle.PRIMARY)]]
        ),
        parse_mode=ParseMode.HTML,
    )
    await status_msg.delete()


dispatcher.add_handler(
    CommandHandler(["reverse", "pp", "p", "grs", "sauce"], reverse_image_search)
)
