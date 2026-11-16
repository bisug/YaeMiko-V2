import asyncio
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

from Mikobot import app, chat_data
from Mikobot.events import callbackquery
from Mikobot.logger import LOGGER
from Mikobot.state import state
from Mikobot.utils.errors import capture_err

CATBOX_API = "https://catbox.moe/user/api.php"
LITTERBOX_API = "https://litterbox.catbox.moe/resources/internals/api.php"

# reqtype must be lowercase; "fileUpload" gets a 412. Pinned by a test.
CATBOX_REQTYPE = "fileupload"
# Litterbox refuses any expiry outside this set, including 48h, with a 412.
LITTERBOX_EXPIRY = ("1h", "12h", "24h", "72h")
LITTERBOX_HOURS = os.environ.get("LITTERBOX_HOURS", "72h")
if LITTERBOX_HOURS not in LITTERBOX_EXPIRY:
    LOGGER.warning(
        "LITTERBOX_HOURS=%r is not one of %s, falling back to 72h",
        LITTERBOX_HOURS,
        LITTERBOX_EXPIRY,
    )
    LITTERBOX_HOURS = "72h"

# 20MB, inherited from the command this replaces, stays under both hosts' limits.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_TIMEOUT = 300
PENDING_PREFIX = "hostup_"
CATBOX_USERHASH = os.environ.get("CATBOX_USERHASH", "").strip()


def _sync_webp_to_png(src: Path, dst: Path) -> None:
    with Image.open(src) as image:
        image.save(dst, "PNG")


async def _upload(path: Path, host: str) -> str:
    """POST the file to Catbox or Litterbox and return the bare URL.

    Both return text rather than JSON, even for errors, so the body is checked
    before the status: a 5xx can still accompany a valid, stored URL.
    """
    data = {"reqtype": CATBOX_REQTYPE}
    url = CATBOX_API
    if host == "litterbox":
        data["time"] = LITTERBOX_HOURS
        url = LITTERBOX_API
    else:
        userhash = globals().get("CATBOX_USERHASH", "")
        if userhash:
            data["userhash"] = userhash

    with open(path, "rb") as handle:
        response = await state.post(
            url,
            data=data,
            files={"fileToUpload": (path.name, handle, "application/octet-stream")},
            timeout=UPLOAD_TIMEOUT,
        )
    body = response.text.strip()
    if body.startswith("http"):
        return body

    # Include the body in the error: a 412's reason is only there, and
    # raise_for_status() would discard it before it reached the log.
    detail = body[:120] or "<empty body>"
    if response.status_code >= 400:
        raise RuntimeError(f"{host} answered HTTP {response.status_code}: {detail}")
    raise RuntimeError(f"{host} answered with no URL: {detail}")


@app.on_message(filters.command(["tgm", "tmg", "telegraph"], prefixes="/"))
@capture_err
async def telegraph_upload(client: Client, message: Message):
    replied = message.reply_to_message
    if not replied or not replied.media:
        await message.reply_text("Reply to a photo, video, animation, or document.")
        return

    if getattr(replied.media, "file_size", 0) > MAX_UPLOAD_BYTES:
        size = MAX_UPLOAD_BYTES // (1024 * 1024)
        await message.reply_text(
            f"That media is too large to upload ({size} MB maximum)."
        )
        return

    # Only the source message is stored: a temp file would be gone before a
    # button is pressed, so the media is re-downloaded on click. These keys
    # share chat_data with admin confirmations and are pruned with them.
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
    await message.reply_text("Where should this be uploaded?", reply_markup=keyboard)


@callbackquery(pattern=r"^hostup_(catbox|litterbox)_[0-9a-f]{8}$")
@capture_err
async def upload_choice(query: CallbackQuery):
    # The decorator passes only the event, not (client, query).
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
        # Use the module-level client; the event has no client attribute.
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
            await asyncio.to_thread(_sync_webp_to_png, upload_path, png_path)
            upload_path = png_path

        fallback_used = False
        catbox_error = None
        try:
            link = await _upload(upload_path, host)
        except Exception as error:
            if host == "catbox":
                # Save the error; Python unbinds 'error' when the block ends.
                catbox_error = error
                LOGGER.warning(
                    "Upload to catbox failed: %s: %s; attempting fallback to litterbox",
                    type(error).__name__,
                    error,
                )
                try:
                    link = await _upload(upload_path, "litterbox")
                    host = "litterbox"
                    fallback_used = True
                except Exception as fallback_error:
                    LOGGER.warning(
                        "Fallback upload to litterbox failed: %s: %s",
                        type(fallback_error).__name__,
                        fallback_error,
                    )
                    await query.message.edit_text(
                        f"Upload to catbox failed: {error}\n"
                        f"Fallback to litterbox failed: {fallback_error}\n"
                        "Nothing was saved."
                    )
                    return
            else:
                LOGGER.warning(
                    "Upload to %s failed: %s: %s", host, type(error).__name__, error
                )
                # Show _upload's message, which carries the host's reason;
                # the exception class alone hides a 412's cause.
                await query.message.edit_text(
                    f"Upload to {host} failed: {error}\nNothing was saved."
                )
                return

    elapsed = time.perf_counter() - started
    if fallback_used:
        note = (
            f"➼ **Catbox upload failed ({catbox_error}); saved to Litterbox instead in {elapsed:.2f} seconds.**\n\n"
            f"➼ **Link:** `{link}`\n\n"
            f"➼ This link expires after {LITTERBOX_HOURS}."
        )
    else:
        note = f"➼ **Uploaded to {host} in {elapsed:.2f} seconds.**\n\n➼ **Link:** `{link}`"
        if host == "litterbox":
            note += f"\n\n➼ This link expires after {LITTERBOX_HOURS}."
    await query.message.edit_text(note)


__help__ = """
➠ *HOSTING*:

» /tgm, /tmg, /telegraph*:* *Reply to media to get a hosted link.*

➠ Pick **Permanent** for a Catbox link that does not expire, or
**Temporary** for a Litterbox link that does. Set `LITTERBOX_HOURS` to
`1h`, `12h`, `24h` or `72h` to change how long the temporary one lasts.
  """

__mod_name__ = "HOSTING"
