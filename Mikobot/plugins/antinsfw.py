# <============================================== IMPORTS =========================================================>
import asyncio
import os
import tempfile

from opennsfw_onnx import NSFWClassifier
from pyrogram import filters

from Database.mongodb.toggle_mongo import is_nsfw_on, nsfw_off, nsfw_on
from Mikobot import BOT_USERNAME, DRAGONS, app
from Mikobot.utils.can_restrict import can_restrict
from Mikobot.utils.errors import capture_err

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
classifier = NSFWClassifier()
NSFW_THRESHOLD = 0.75
MAX_FILE_SIZE = 3 * 1024 * 1024


async def _scan(file_path: str):
    return await asyncio.to_thread(classifier.classify, file_path)


def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def get_file_id_from_message(message):
    file_id = None
    if message.document:
        if int(message.document.file_size) > MAX_FILE_SIZE:
            return
        mime_type = message.document.mime_type or ""
        if not mime_type.startswith("image/"):
            return
        file_id = message.document.file_id

    if message.sticker:
        if message.sticker.is_animated:
            if not message.sticker.thumbs:
                return
            file_id = message.sticker.thumbs[0].file_id
        else:
            file_id = message.sticker.file_id

    if message.photo:
        file_id = message.photo.file_id

    if message.animation:
        if not message.animation.thumbs:
            return
        file_id = message.animation.thumbs[0].file_id

    if message.video:
        if not message.video.thumbs:
            return
        file_id = message.video.thumbs[0].file_id

    if message.video_note:
        if not message.video_note.thumbs:
            return
        file_id = message.video_note.thumbs[0].file_id
    return file_id


@app.on_message(
    (
        filters.document
        | filters.photo
        | filters.sticker
        | filters.animation
        | filters.video
        | filters.VIDEO_NOTE
    )
    & ~filters.private,
    group=8,
)
@capture_err
async def detect_nsfw(_, message):
    if not await is_nsfw_on(message.chat.id):
        return
    if not message.from_user:
        return
    file_id = await get_file_id_from_message(message)
    if not file_id:
        return
    with tempfile.NamedTemporaryFile(suffix=".media", delete=False) as temp:
        file = temp.name
    file = await _.download_media(file_id, file_name=file)
    try:
        result = await _scan(file)
    except Exception as error:
        await message.reply_text(f"NSFW scan failed: {error}")
        return
    finally:
        if file and os.path.exists(file):
            os.remove(file)
    if result.nsfw < NSFW_THRESHOLD:
        return
    if message.from_user.id in DRAGONS:
        return
    try:
        await message.delete()
    except Exception:
        return
    await message.reply_text(
        f"""
**🔞 NSFW Image Detected & Deleted Successfully!**

**✪ User:** {message.from_user.mention} [`{message.from_user.id}`]
**✪ Safe:** `{result.sfw:.2%}`
**✪ NSFW score:** `{result.nsfw:.2%}`
"""
    )


@app.on_message(filters.command(["nsfwscan", f"nsfwscan@{BOT_USERNAME}"]))
@capture_err
async def nsfw_scan_command(_, message):
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to an image/document/sticker/animation to scan it."
        )
        return
    reply = message.reply_to_message
    if (
        not reply.document
        and not reply.photo
        and not reply.sticker
        and not reply.animation
        and not reply.video
        and not reply.video_note
    ):
        await message.reply_text(
            "Reply to an image/document/sticker/animation to scan it."
        )
        return
    m = await message.reply_text("Scanning")
    file_id = await get_file_id_from_message(reply)
    if not file_id:
        return await m.edit("Something wrong happened.")
    with tempfile.NamedTemporaryFile(suffix=".media", delete=False) as temp:
        file = temp.name
    file = await _.download_media(file_id, file_name=file)
    try:
        result = await _scan(file)
    except Exception as error:
        return await m.edit(f"NSFW scan failed: {error}")
    finally:
        if file and os.path.exists(file):
            os.remove(file)
    await m.edit(
        f"**➢ Safe:** `{result.sfw:.2%}`\n"
        f"**➢ NSFW:** `{result.nsfw:.2%}`\n"
        f"**➢ Flagged:** `{result.nsfw >= NSFW_THRESHOLD}`"
    )


@app.on_message(
    filters.command(["antinsfw", f"antinsfw@{BOT_USERNAME}"]) & ~filters.private
)
@can_restrict
async def nsfw_enable_disable(_, message):
    if len(message.command) != 2:
        await message.reply_text("Usage: /antinsfw [on/off]")
        return
    status = message.text.split(None, 1)[1].strip()
    status = status.lower()
    chat_id = message.chat.id
    if status in ("on", "yes"):
        if await is_nsfw_on(chat_id):
            await message.reply_text("Antinsfw is already enabled.")
            return
        await nsfw_on(chat_id)
        await message.reply_text(
            "Enabled AntiNSFW System. I will Delete Messages Containing Inappropriate Content."
        )
    elif status in ("off", "no"):
        if not await is_nsfw_on(chat_id):
            await message.reply_text("Antinsfw is already disabled.")
            return
        await nsfw_off(chat_id)
        await message.reply_text("Disabled AntiNSFW System.")
    else:
        await message.reply_text("Unknown Suffix, Use /antinsfw [on/off]")


# <=================================================== HELP ====================================================>


__mod_name__ = "ANTI-NSFW"

__help__ = """
*🔞 Helps in detecting NSFW material and removing it*.

➠ *Usage:*

» /antinsfw [on/off]: Enables Anti-NSFW system.

» /nsfwscan <reply to message>: Scans the file replied to.
"""
# <================================================ END =======================================================>
