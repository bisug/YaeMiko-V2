import asyncio
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus

import Database.sql.toggle_sql as sql
from Mikobot import BOT_USERNAME
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.utils.can_restrict import can_restrict
from Mikobot.utils.errors import capture_err

classifier = None
NSFW_THRESHOLD = 0.55
MAX_FILE_SIZE = 10 * 1024 * 1024
SCAN_CACHE_MAX = 2000
SCAN_CACHE: OrderedDict[str, object] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def get_cached_result(unique_id: str | None):
    if not unique_id:
        return None
    with _CACHE_LOCK:
        res = SCAN_CACHE.get(unique_id)
        if res is not None:
            SCAN_CACHE.move_to_end(unique_id)
            return res
    return None


def set_cached_result(unique_id: str | None, result):
    if not unique_id or result is None:
        return
    with _CACHE_LOCK:
        SCAN_CACHE[unique_id] = result
        if len(SCAN_CACHE) > SCAN_CACHE_MAX:
            SCAN_CACHE.popitem(last=False)


def get_classifier():
    global classifier
    if classifier is None:
        try:
            from opennsfw_onnx import NSFWClassifier

            classifier = NSFWClassifier(
                intra_op_num_threads=2,
                jpeg_reencode=False,
            )
            classifier.warmup()
        except ImportError as error:
            raise RuntimeError(
                "NSFW scanning is unavailable (requires opennsfw-onnx and onnxruntime)."
            ) from error
    return classifier


def _classify_sync(target):
    if hasattr(target, "seek"):
        target.seek(0)
    c = get_classifier()
    return c.classify(target)


async def _scan(target):
    return await asyncio.to_thread(_classify_sync, target)


def select_best_thumb(thumbs):
    if not thumbs or not isinstance(thumbs, (list, tuple)):
        return None
    sized = []
    for t in thumbs:
        fid = getattr(t, "file_id", None)
        w = getattr(t, "width", 0)
        h = getattr(t, "height", 0)
        if (
            fid
            and isinstance(w, (int, float))
            and isinstance(h, (int, float))
            and max(w, h) >= 200
        ):
            sized.append((max(w, h), fid))
    if sized:
        sized.sort(key=lambda item: item[0])
        return sized[0][1]
    for t in reversed(thumbs):
        fid = getattr(t, "file_id", None)
        if fid and isinstance(fid, str):
            return fid
    return None


def get_media_unique_id(message) -> str | None:
    for attr in ("photo", "sticker", "animation", "video", "video_note", "document"):
        obj = getattr(message, attr, None)
        if obj and isinstance(getattr(obj, "file_unique_id", None), str):
            return obj.file_unique_id
    return None


def get_media_from_message(message):
    if message.document:
        mime = message.document.mime_type or ""
        thumb_id = select_best_thumb(getattr(message.document, "thumbs", None))
        if mime.startswith("image/"):
            file_id = thumb_id or message.document.file_id
            if not thumb_id and int(message.document.file_size or 0) > MAX_FILE_SIZE:
                return None, None
            return file_id, "image"
        if mime.startswith("video/"):
            if thumb_id:
                return thumb_id, "image"
            if int(message.document.file_size or 0) > MAX_FILE_SIZE:
                return None, None
            return message.document.file_id, "video"
        return None, None

    if message.sticker:
        if getattr(message.sticker, "is_animated", False):
            return None, None
        if getattr(message.sticker, "is_video", False):
            thumb_id = select_best_thumb(getattr(message.sticker, "thumbs", None))
            if thumb_id:
                return thumb_id, "image"
            if message.sticker.file_size and message.sticker.file_size > MAX_FILE_SIZE:
                return None, None
            return message.sticker.file_id, "video"
        if message.sticker.file_size and message.sticker.file_size > MAX_FILE_SIZE:
            return None, None
        return message.sticker.file_id, "image"

    if message.photo:
        thumb_id = select_best_thumb(getattr(message.photo, "thumbs", None))
        file_id = thumb_id or message.photo.file_id
        if (
            not thumb_id
            and message.photo.file_size
            and message.photo.file_size > MAX_FILE_SIZE
        ):
            return None, None
        return file_id, "image"

    if message.animation:
        thumb_id = select_best_thumb(getattr(message.animation, "thumbs", None))
        if thumb_id:
            return thumb_id, "image"
        if message.animation.file_size and message.animation.file_size > MAX_FILE_SIZE:
            return None, None
        return message.animation.file_id, "video"

    if message.video:
        thumb_id = select_best_thumb(getattr(message.video, "thumbs", None))
        if thumb_id:
            return thumb_id, "image"
        if message.video.file_size and message.video.file_size > MAX_FILE_SIZE:
            return None, None
        return message.video.file_id, "video"

    if message.video_note:
        thumb_id = select_best_thumb(getattr(message.video_note, "thumbs", None))
        if thumb_id:
            return thumb_id, "image"
        if (
            message.video_note.file_size
            and message.video_note.file_size > MAX_FILE_SIZE
        ):
            return None, None
        return message.video_note.file_id, "video"

    return None, None


async def prepare_scan_file(client, message, temp_dir=None):
    file_id, media_type = get_media_from_message(message)
    if not file_id:
        return None

    # In-memory fast path for images: avoids all disk I/O and temp dir churn
    if not temp_dir and media_type == "image":
        try:
            bio = await client.download_media(file_id, in_memory=True)
            if bio:
                if hasattr(bio, "seek"):
                    bio.seek(0)
                return bio
        except Exception as exc:
            LOGGER.debug("In-memory media download failed, falling back: %s", exc)

    with_temp = temp_dir or tempfile.gettempdir()
    msg_id = getattr(message, "id", None) or "scan"
    chat_id = getattr(getattr(message, "chat", None), "id", "na")
    source = Path(with_temp) / f"source_{chat_id}_{msg_id}.media"
    try:
        downloaded = await client.download_media(file_id, file_name=str(source))
    except Exception as exc:
        LOGGER.debug("Media download failed for scan: %s", exc)
        return None
    if not downloaded:
        return None

    if media_type == "image":
        try:
            from PIL import Image

            with Image.open(downloaded) as img:
                img.verify()
            return str(downloaded)
        except Exception:
            pass

    output = Path(with_temp) / f"frame_{msg_id}.png"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(downloaded),
        "-frames:v",
        "1",
        "-f",
        "image2",
        str(output),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(), timeout=10)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return None
    finally:
        try:
            if Path(downloaded).exists():
                Path(downloaded).unlink()
        except Exception:
            pass

    if process.returncode != 0 or not output.exists():
        return None
    return str(output)


@on_message(
    (
        filters.document
        | filters.photo
        | filters.sticker
        | filters.animation
        | filters.video
        | filters.video_note
    )
    & ~filters.private,
    chained=True,
)
@capture_err
async def detect_nsfw(client, message):
    if not sql.is_nsfw_on(message.chat.id):
        return
    if not message.from_user and not message.sender_chat:
        return
    if not get_media_from_message(message)[0]:
        return

    unique_id = get_media_unique_id(message)
    result = get_cached_result(unique_id)

    if result is None:
        target = await prepare_scan_file(client, message)
        if not target:
            return
        try:
            result = await _scan(target)
            set_cached_result(unique_id, result)
        except Exception as error:
            LOGGER.debug("NSFW scan skipped for message %s: %s", message.id, error)
            return
        finally:
            if isinstance(target, (str, Path)):
                try:
                    Path(target).unlink(missing_ok=True)
                except Exception:
                    pass

    if result.nsfw < NSFW_THRESHOLD:
        return

    deleted = True
    try:
        await message.delete()
    except Exception as exc:
        deleted = False
        LOGGER.warning(
            "Failed to delete NSFW message %s in chat %s: %s",
            message.id,
            message.chat.id,
            exc,
        )

    user_info = (
        f"{message.from_user.mention} [`{message.from_user.id}`]"
        if message.from_user
        else (
            f"<b>{getattr(message.sender_chat, 'title', 'Channel')}</b> [`{getattr(message.sender_chat, 'id', '')}`]"
            if message.sender_chat
            else "Anonymous"
        )
    )

    thread_id = getattr(message, "message_thread_id", None)
    if not deleted:
        await client.send_message(
            chat_id=message.chat.id,
            text=(
                f"🔞 **NSFW Content Detected!**\n\n"
                f"**✪ User:** {user_info}\n"
                f"**✪ Safe:** `{result.sfw:.2%}`\n"
                f"**✪ NSFW score:** `{result.nsfw:.2%}`\n\n"
                f"⚠️ *Could not delete message: Please grant me 'Delete Messages' admin permission!*"
            ),
            message_thread_id=thread_id,
        )
        return

    await client.send_message(
        chat_id=message.chat.id,
        text=f"""
**🔞 NSFW Image Detected & Deleted Successfully!**

**✪ User:** {user_info}
**✪ Safe:** `{result.sfw:.2%}`
**✪ NSFW score:** `{result.nsfw:.2%}`
""",
        message_thread_id=thread_id,
    )


@on_message(
    filters.command(["nsfwscan", f"nsfwscan@{BOT_USERNAME}"]),
    chained=True,
)
@capture_err
async def nsfw_scan_command(client, message):
    if not message.reply_to_message:
        await message.reply_text(
            "Reply to an image/document/sticker/animation/video to scan it."
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
            "Reply to an image/document/sticker/animation/video to scan it."
        )
        return
    if getattr(reply.sticker, "is_animated", False):
        await message.reply_text(
            "Animated stickers (.tgs) are vector animations and cannot be scanned for NSFW content."
        )
        return
    m = await message.reply_text("Scanning...")
    if not get_media_from_message(reply)[0]:
        return await m.edit(
            "The media could not be processed for scanning (unsupported format or exceeds size limit)."
        )

    unique_id = get_media_unique_id(reply)
    result = get_cached_result(unique_id)

    if result is None:
        target = await prepare_scan_file(client, reply)
        if not target:
            return await m.edit("The media could not be converted for scanning.")
        try:
            result = await _scan(target)
            set_cached_result(unique_id, result)
        except Exception as error:
            LOGGER.exception("Manual NSFW scan failed: %s", error)
            return await m.edit(f"NSFW scan failed: {error}")
        finally:
            if isinstance(target, (str, Path)):
                try:
                    Path(target).unlink(missing_ok=True)
                except Exception:
                    pass

    await m.edit(
        f"**➢ Safe:** `{result.sfw:.2%}`\n"
        f"**➢ NSFW:** `{result.nsfw:.2%}`\n"
        f"**➢ Flagged:** `{result.nsfw >= NSFW_THRESHOLD}`"
    )


@on_message(
    filters.command(["antinsfw", f"antinsfw@{BOT_USERNAME}"]) & ~filters.private,
    chained=True,
)
@can_restrict
async def nsfw_enable_disable(client, message):
    chat_id = message.chat.id
    if len(message.command) != 2:
        current_status = "enabled" if sql.is_nsfw_on(chat_id) else "disabled"
        await message.reply_text(
            f"AntiNSFW is currently **{current_status}** in this chat.\n\n"
            f"Usage: `/antinsfw [on/off]`"
        )
        return
    status = message.text.split(None, 1)[1].strip().lower()
    if status in ("on", "yes"):
        if sql.is_nsfw_on(chat_id):
            await message.reply_text("AntiNSFW is already enabled.")
            return
        sql.nsfw_on(chat_id)

        can_delete = True
        try:
            bot_member = await client.get_chat_member(chat_id, "me")
            privileges = getattr(bot_member, "privileges", None)
            if privileges:
                can_delete = bool(getattr(privileges, "can_delete_messages", False))
            elif getattr(bot_member, "status", None) != ChatMemberStatus.ADMINISTRATOR:
                can_delete = False
        except Exception:
            pass

        if not can_delete:
            await message.reply_text(
                "Enabled AntiNSFW System.\n\n"
                "⚠️ **Warning:** I do not have permission to delete messages! "
                "Please promote me to admin with 'Delete Messages' permission so I can remove NSFW content."
            )
        else:
            await message.reply_text(
                "Enabled AntiNSFW System. I will Delete Messages Containing Inappropriate Content."
            )
    elif status in ("off", "no"):
        if not sql.is_nsfw_on(chat_id):
            await message.reply_text("AntiNSFW is already disabled.")
            return
        sql.nsfw_off(chat_id)
        await message.reply_text("Disabled AntiNSFW System.")
    else:
        await message.reply_text("Unknown suffix. Use /antinsfw [on/off]")


__mod_name__ = "Anti-NSFW"

__help__ = """
🔞 Detects NSFW material and removes it.

Commands:
/antinsfw [on/off]: Enable or disable NSFW filtering in this group.
/nsfwscan <reply to message>: Scan the replied-to file for NSFW content.
"""
