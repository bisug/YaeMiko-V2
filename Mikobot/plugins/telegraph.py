# <============================================== IMPORTS =========================================================>
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import LOGGER, app, chat_data
from Mikobot.events import callbackquery
from Mikobot.state import state
from Mikobot.utils.errors import capture_err

# <=======================================================================================================>

CATBOX_API = "https://catbox.moe/user/api.php"
LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"

# reqtype has to be lowercase. The form shown nearly everywhere online,
# "fileUpload", is answered with 412 "No request type given?", confirmed with
# a probe upload, so it is pinned by a test rather than left to a comment.
CATBOX_REQTYPE = "fileupload"
# Anything outside this set is refused with 412 "No expire time specified.",
# 48h included.
LITTERBOX_EXPIRY = ("1h", "12h", "24h", "72h")
LITTERBOX_HOURS = os.environ.get("LITTERBOX_HOURS", "72h")
if LITTERBOX_HOURS not in LITTERBOX_EXPIRY:
    LOGGER.warning(
        "LITTERBOX_HOURS=%r is not one of %s, falling back to 72h",
        LITTERBOX_HOURS,
        LITTERBOX_EXPIRY,
    )
    LITTERBOX_HOURS = "72h"

# Catbox takes 200MB and Litterbox 1GB. 20MB is kept from the Telegraph command
# this replaces, so neither host is ever asked for a file it may refuse.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_TIMEOUT = 300
PENDING_PREFIX = "hostup_"


async def _upload(path: Path, host: str) -> str:
    """POST the file to Catbox or Litterbox and return the URL as plain text.

    Both answer with the bare URL rather than JSON, and both answer errors as
    bare text as well. Catbox was also seen replying 200 with an empty body
    while rate limiting, so the response is checked instead of assumed.
    """
    data = {"reqtype": CATBOX_REQTYPE}
    url = CATBOX_API
    if host == "litterbox":
        data["time"] = LITTERBOX_HOURS
        url = LITTERBOX_API

    with open(path, "rb") as handle:
        response = await state.post(
            url,
            data=data,
            files={"fileToUpload": (path.name, handle, "application/octet-stream")},
            timeout=UPLOAD_TIMEOUT,
        )
    response.raise_for_status()
    body = response.text.strip()
    if not body.startswith("http"):
        raise RuntimeError(f"{host} answered with no URL: {body[:80]!r}")
    return body


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.command(["tgm", "tmg", "telegraph"], prefixes="/"))
@capture_err
async def telegraph_upload(client: Client, message: Message):
    replied = message.reply_to_message
    if not replied or not replied.media:
        await message.reply("Reply to a photo, video, animation, or document.")
        return

    if getattr(replied.media, "file_size", 0) > MAX_UPLOAD_BYTES:
        size = MAX_UPLOAD_BYTES // (1024 * 1024)
        await message.reply(f"That media is too large to upload ({size} MB maximum).")
        return

    # The file is deliberately not held here. The TemporaryDirectory this used
    # to write into is deleted as soon as the handler returns, long before a
    # button gets pressed, so only the source message is remembered and it is
    # re-downloaded on click. These keys live in the same chat_data as the
    # pending admin confirmations and are pruned by the same store.
    token = uuid4().hex[:8]
    chat_data[f"{PENDING_PREFIX}{token}"] = {
        "chat_id": message.chat.id,
        "message_id": replied.id,
        "user_id": message.from_user.id,
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔒 Permanent (Catbox)",
                    callback_data=f"hostup_catbox_{token}",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🕐 Temporary ({LITTERBOX_HOURS}, Litterbox)",
                    callback_data=f"hostup_litterbox_{token}",
                    style=ButtonStyle.PRIMARY,
                )
            ],
        ]
    )
    await message.reply("Where should this be uploaded?", reply_markup=keyboard)


@callbackquery(pattern=r"^hostup_(catbox|litterbox)_[0-9a-f]{8}$")
@capture_err
async def upload_choice(query: CallbackQuery):
    # One argument, not (client, query): the callbackquery decorator wraps the
    # handler so it is handed only the event.
    _prefix, host, token = query.data.split("_")

    key = f"{PENDING_PREFIX}{token}"
    pending = chat_data.get(key)
    if not pending:
        await query.answer("This request has expired.", show_alert=True)
        return
    # Only whoever ran the command may use its button.
    if query.from_user.id != pending["user_id"]:
        await query.answer(
            "Only the person who used /tgm can click that.", show_alert=True
        )
        return
    # Spent, whether or not the upload then succeeds, so one button is one try.
    chat_data.pop(key, None)

    await query.answer("Uploading…")
    started = time.perf_counter()

    try:
        # The callbackquery decorator hands over only the event, so the module
        # level client is used rather than a private attribute off the query.
        source = await app.get_messages(
            pending["chat_id"], message_ids=pending["message_id"]
        )
    except Exception:
        LOGGER.exception("Could not re-read the source message for %s", host)
        await query.message.edit_text("That message could not be read any more.")
        return

    if not source or not source.media:
        await query.message.edit_text("That message could not be read any more.")
        return

    with tempfile.TemporaryDirectory(prefix="yae-upload-") as temp_dir:
        downloaded = await app.download_media(source, file_name=temp_dir + os.sep)
        if not downloaded or not Path(downloaded).is_file():
            await query.message.edit_text("That media could not be downloaded.")
            return

        upload_path = Path(downloaded)
        if upload_path.suffix.lower() == ".webp":
            png_path = upload_path.with_suffix(".png")
            with Image.open(upload_path) as image:
                image.save(png_path, "PNG")
            upload_path = png_path

        try:
            link = await _upload(upload_path, host)
        except Exception as error:
            LOGGER.warning(
                "Upload to %s failed: %s: %s", host, type(error).__name__, error
            )
            await query.message.edit_text(
                f"Upload to {host} failed ({type(error).__name__}). "
                "Nothing was saved."
            )
            return

    elapsed = time.perf_counter() - started
    note = (
        f"➼ **Uploaded to {host} in {elapsed:.2f} seconds.**\n\n"
        f"➼ **Link:** `{link}`"
    )
    if host == "litterbox":
        note += f"\n\n➼ This link expires after {LITTERBOX_HOURS}."
    await query.message.edit_text(note)

# <=================================================== HELP ====================================================>
__help__ = """
➠ *HOSTING*:

» /tgm, /tmg, /telegraph*:* *Reply to media to get a hosted link.*

➠ Pick **Permanent** for a Catbox link that does not expire, or
**Temporary** for a Litterbox link that does. Set `LITTERBOX_HOURS` to
`1h`, `12h`, `24h` or `72h` to change how long the temporary one lasts.
  """

__mod_name__ = "HOSTING"
# <================================================ END =======================================================>
