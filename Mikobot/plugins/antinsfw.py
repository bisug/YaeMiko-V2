# <============================================== IMPORTS =========================================================>
import asyncio
import os
import tempfile
from pathlib import Path

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


def get_media_from_message(message):
    if message.document:
        if int(message.document.file_size or 0) > MAX_FILE_SIZE:
            return None, None
        if not (message.document.mime_type or "").startswith("image/"):
            return None, None
        return message.document.file_id, "image"
    if message.sticker:
        if message.sticker.is_animated:
            if message.sticker.file_size and message.sticker.file_size > MAX_FILE_SIZE:
                return None, None
            return (
                (message.sticker.thumbs[0].file_id, "image")
                if message.sticker.thumbs
                else (None, None)
            )
        if message.sticker.file_size and message.sticker.file_size > MAX_FILE_SIZE:
            return None, None
        return message.sticker.file_id, "image"
    if message.photo:
        if message.photo.file_size and message.photo.file_size > MAX_FILE_SIZE:
            return None, None
        return message.photo.file_id, "image"
    if message.animation:
        if message.animation.file_size and message.animation.file_size > MAX_FILE_SIZE:
            return None, None
        return message.animation.file_id, "video"
    if message.video:
        if message.video.file_size and message.video.file_size > MAX_FILE_SIZE:
            return None, None
        return message.video.file_id, "video"
    if message.video_note:
        if message.video_note.file_size and message.video_note.file_size > MAX_FILE_SIZE:
            return None, None
        return message.video_note.file_id, "video"
    return None, None


async def prepare_scan_file(client, message, temp_dir):
    file_id, media_type = get_media_from_message(message)
    if not file_id:
        return None
    source = Path(temp_dir) / "source.media"
    downloaded = await client.download_media(file_id, file_name=str(source))
    if not downloaded:
        return None
    if media_type == "image":
        return str(downloaded)
    output = Path(temp_dir) / "frame.png"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", str(downloaded), "-frames:v", "1",
        "-f", "image2", str(output), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=20)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None

    if process.returncode != 0 or not output.exists():
        return None
    return str(output)


@app.on_message(
    (
        filters.document
        | filters.photo
        | filters.sticker
        | filters.animation
        | filters.video
        | filters.video_note
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
    if not get_media_from_message(message)[0]:
        return
    with tempfile.TemporaryDirectory(prefix="yae-nsfw-") as temp_dir:
        file = await prepare_scan_file(_, message, temp_dir)
        if not file:
            return
        try:
            result = await _scan(file)
        except Exception as error:
            await message.reply_text(f"NSFW scan failed: {error}")
            return
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
    if not get_media_from_message(reply)[0]:
        return await m.edit("Something wrong happened.")
    with tempfile.TemporaryDirectory(prefix="yae-nsfw-") as temp_dir:
        file = await prepare_scan_file(_, reply, temp_dir)
        if not file:
            return await m.edit("The media could not be converted for scanning.")
        try:
            result = await _scan(file)
        except Exception as error:
            return await m.edit(f"NSFW scan failed: {error}")
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
