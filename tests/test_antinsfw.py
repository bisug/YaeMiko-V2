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
    assert "Animated stickers (.tgs) are vector animations" in msg.reply_text.call_args[0][0]
