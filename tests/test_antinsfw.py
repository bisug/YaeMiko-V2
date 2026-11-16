from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from pyrogram.types import Message, Photo, Sticker, Thumbnail, Video

from Mikobot.plugins import antinsfw


def test_get_media_from_message_animated_sticker():
    msg = MagicMock(spec=Message)
    msg.document = None
    msg.photo = None
    msg.animation = None
    msg.video = None
    msg.video_note = None
    msg.sticker = MagicMock(spec=Sticker)
    msg.sticker.is_animated = True
    msg.sticker.is_video = False
    msg.sticker.file_size = 1000

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id is None
    assert media_type is None


def test_get_media_from_message_video_sticker():
    msg = MagicMock(spec=Message)
    msg.document = None
    msg.photo = None
    msg.animation = None
    msg.video = None
    msg.video_note = None
    msg.sticker = MagicMock(spec=Sticker)
    msg.sticker.is_animated = False
    msg.sticker.is_video = True
    msg.sticker.file_id = "video_sticker_file_id"
    msg.sticker.file_size = 1000

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "video_sticker_file_id"
    assert media_type == "video"


def test_get_media_from_message_static_sticker():
    msg = MagicMock(spec=Message)
    msg.document = None
    msg.photo = None
    msg.animation = None
    msg.video = None
    msg.video_note = None
    msg.sticker = MagicMock(spec=Sticker)
    msg.sticker.is_animated = False
    msg.sticker.is_video = False
    msg.sticker.file_id = "static_sticker_file_id"
    msg.sticker.file_size = 1000

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "static_sticker_file_id"
    assert media_type == "image"


def test_get_media_from_message_video_with_thumbs():
    msg = MagicMock(spec=Message)
    msg.document = None
    msg.photo = None
    msg.sticker = None
    msg.animation = None
    msg.video_note = None
    msg.video = MagicMock(spec=Video)
    msg.video.file_size = 10_000_000  # large video
    thumb = MagicMock(spec=Thumbnail)
    thumb.file_id = "thumb_file_id"
    msg.video.thumbs = [thumb]

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "thumb_file_id"
    assert media_type == "image"


@pytest.mark.asyncio
async def test_prepare_scan_file_valid_image():
    client = AsyncMock()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_img = Path(temp_dir) / "test.png"
        Image.new("RGB", (50, 50)).save(test_img)
        client.download_media.return_value = test_img

        msg = MagicMock(spec=Message)
        msg.document = None
        msg.sticker = None
        msg.animation = None
        msg.video = None
        msg.video_note = None
        msg.photo = MagicMock(spec=Photo)
        msg.photo.file_size = 500
        msg.photo.file_id = "photo_123"

        scannable = await antinsfw.prepare_scan_file(client, msg, temp_dir)
        assert scannable == str(test_img)


@pytest.mark.asyncio
async def test_detect_nsfw_ignores_animated_sticker():
    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.from_user.id = 999
    msg.document = None
    msg.photo = None
    msg.animation = None
    msg.video = None
    msg.video_note = None
    msg.sticker = MagicMock()
    msg.sticker.is_animated = True

    with patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True):
        await antinsfw.detect_nsfw(client, msg)

    # Must not send any message to chat
    client.download_media.assert_not_called()
    msg.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_nsfwscan_command_animated_sticker_friendly_message():
    client = AsyncMock()
    msg = MagicMock(spec=Message)
    reply = MagicMock(spec=Message)
    msg.reply_to_message = reply

    reply.document = None
    reply.photo = None
    reply.animation = None
    reply.video = None
    reply.video_note = None
    reply.sticker = MagicMock(spec=Sticker)
    reply.sticker.is_animated = True

    msg.reply_text = AsyncMock()

    await antinsfw.nsfw_scan_command(client, msg)

    msg.reply_text.assert_called_once()
    assert (
        "Animated stickers (.tgs) are vector animations"
        in msg.reply_text.call_args[0][0]
    )


@pytest.mark.asyncio
async def test_detect_nsfw_deletes_and_notifies_even_for_dev_user():
    from collections import namedtuple

    Prediction = namedtuple("Prediction", ["sfw", "nsfw"])

    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.message_thread_id = None
    msg.from_user = MagicMock()
    msg.from_user.id = 123456  # Even if dev/owner
    msg.from_user.mention = "@owner"
    msg.sender_chat = None
    msg.document = None
    msg.photo = MagicMock()
    msg.photo.file_size = 500
    msg.photo.file_id = "test_photo_id"
    msg.sticker = None
    msg.animation = None
    msg.video = None
    msg.video_note = None

    msg.delete = AsyncMock()

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True),
        patch(
            "Mikobot.plugins.antinsfw.prepare_scan_file", return_value="/tmp/test.png"
        ),
        patch(
            "Mikobot.plugins.antinsfw._scan", return_value=Prediction(sfw=0.1, nsfw=0.9)
        ),
    ):
        await antinsfw.detect_nsfw(client, msg)

    msg.delete.assert_called_once()
    client.send_message.assert_called_once()
    assert (
        "NSFW Image Detected & Deleted Successfully"
        in client.send_message.call_args[1]["text"]
    )


@pytest.mark.asyncio
async def test_detect_nsfw_warns_when_bot_cannot_delete():
    from collections import namedtuple

    Prediction = namedtuple("Prediction", ["sfw", "nsfw"])

    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.message_thread_id = None
    msg.from_user = MagicMock()
    msg.from_user.id = 99999
    msg.from_user.mention = "@user"
    msg.sender_chat = None
    msg.document = None
    msg.photo = MagicMock()
    msg.photo.file_size = 500
    msg.photo.file_id = "test_photo_id"
    msg.sticker = None
    msg.animation = None
    msg.video = None
    msg.video_note = None

    msg.delete = AsyncMock(side_effect=Exception("ChatAdminRequired"))

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True),
        patch(
            "Mikobot.plugins.antinsfw.prepare_scan_file", return_value="/tmp/test.png"
        ),
        patch(
            "Mikobot.plugins.antinsfw._scan", return_value=Prediction(sfw=0.1, nsfw=0.9)
        ),
    ):
        await antinsfw.detect_nsfw(client, msg)

    msg.delete.assert_called_once()
    client.send_message.assert_called_once()
    assert "Could not delete message" in client.send_message.call_args[1]["text"]


@pytest.mark.asyncio
async def test_nsfw_enable_disable_status_query():
    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.command = ["antinsfw"]
    msg.reply_text = AsyncMock()

    with patch("Database.sql.toggle_sql.is_nsfw_on", return_value=False):
        await antinsfw.nsfw_enable_disable.__wrapped__(client, msg)

    msg.reply_text.assert_called_once()
    assert "AntiNSFW is currently **disabled**" in msg.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_nsfw_enable_disable_warns_when_bot_lacks_delete_rights():
    from pyrogram.enums import ChatMemberStatus

    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.command = ["antinsfw", "on"]
    msg.text = "/antinsfw on"
    msg.reply_text = AsyncMock()

    bot_member = MagicMock()
    bot_member.status = ChatMemberStatus.MEMBER
    bot_member.privileges = None
    client.get_chat_member.return_value = bot_member

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=False),
        patch("Database.sql.toggle_sql.nsfw_on") as mock_on,
    ):
        await antinsfw.nsfw_enable_disable.__wrapped__(client, msg)

    mock_on.assert_called_once_with(-10012345)
    msg.reply_text.assert_called_once()
    assert "Warning" in msg.reply_text.call_args[0][0]
    assert "permission to delete messages" in msg.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_prepare_scan_file_in_memory_fast_path():
    import io

    client = AsyncMock()
    fake_bio = io.BytesIO(b"fake_image_bytes")
    client.download_media.return_value = fake_bio

    msg = MagicMock()
    msg.document = None
    msg.sticker = None
    msg.animation = None
    msg.video = None
    msg.video_note = None
    msg.photo = MagicMock()
    msg.photo.file_size = 500
    msg.photo.file_id = "photo_in_mem_123"
    msg.photo.thumbs = None

    result = await antinsfw.prepare_scan_file(client, msg)

    client.download_media.assert_called_once_with("photo_in_mem_123", in_memory=True)
    assert result is fake_bio


@pytest.mark.asyncio
async def test_lru_cache_deduplicates_media_scans():
    from collections import namedtuple

    Prediction = namedtuple("Prediction", ["sfw", "nsfw"])

    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = -10012345
    msg.message_thread_id = None
    msg.from_user = MagicMock()
    msg.from_user.id = 555
    msg.from_user.mention = "@user"
    msg.sender_chat = None
    msg.document = None
    msg.photo = MagicMock()
    msg.photo.file_size = 500
    msg.photo.file_id = "repeat_photo_id"
    msg.photo.file_unique_id = "unique_hash_999"
    msg.photo.thumbs = None
    msg.sticker = None
    msg.animation = None
    msg.video = None
    msg.video_note = None

    msg.delete = AsyncMock()

    # Pre-populate cache
    antinsfw.set_cached_result("unique_hash_999", Prediction(sfw=0.05, nsfw=0.95))

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True),
        patch("Mikobot.plugins.antinsfw.prepare_scan_file") as mock_prep,
        patch("Mikobot.plugins.antinsfw._scan") as mock_scan,
    ):
        await antinsfw.detect_nsfw(client, msg)

    # prepare_scan_file and _scan must NOT be called because cache matched
    mock_prep.assert_not_called()
    mock_scan.assert_not_called()
    msg.delete.assert_called_once()


def test_select_best_thumb_logic():
    class Thumb:
        def __init__(self, fid, w, h):
            self.file_id = fid
            self.width = w
            self.height = h

    t1 = Thumb("tiny", 100, 100)
    t2 = Thumb("optimal", 320, 240)
    t3 = Thumb("huge", 1280, 720)

    # Should select optimal (closest to 224 without being too small or huge)
    best = antinsfw.select_best_thumb([t1, t2, t3])
    assert best == "optimal"
