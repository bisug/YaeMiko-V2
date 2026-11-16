from __future__ import annotations

import tempfile
from collections import namedtuple
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
from pyrogram.types import Message, Photo, Sticker, Thumbnail, Video

from Mikobot.plugins import antinsfw

Prediction = namedtuple("Prediction", ["sfw", "nsfw"])

NSFW_CHAT_ID = -10012345
SCAN_PATH = "/tmp/test.png"
NSFW_PREDICTION = Prediction(sfw=0.1, nsfw=0.9)

MEDIA_ATTRS = ("document", "photo", "animation", "video", "video_note", "sticker")


def _media_message(spec=Message, **media):
    """A message with every media slot initialized, so tests set only what matters."""
    msg = MagicMock(spec=spec)
    for name in MEDIA_ATTRS:
        setattr(msg, name, media.get(name))
    return msg


def _nsfw_message(
    *, user_id=99999, mention="@user", photo_id="test_photo_id", unique_id=None
):
    msg = _media_message(spec=None, photo=MagicMock(file_size=500, file_id=photo_id))
    if unique_id is not None:
        msg.photo.file_unique_id = unique_id
    msg.chat.id = NSFW_CHAT_ID
    msg.message_thread_id = None
    msg.from_user = MagicMock(id=user_id, mention=mention)
    msg.sender_chat = None
    msg.delete = AsyncMock()
    return msg


def test_get_media_from_message_animated_sticker():
    msg = _media_message(
        sticker=MagicMock(
            spec=Sticker, is_animated=True, is_video=False, file_size=1000
        )
    )

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id is None
    assert media_type is None


def test_get_media_from_message_video_sticker():
    msg = _media_message(
        sticker=MagicMock(
            spec=Sticker,
            is_animated=False,
            is_video=True,
            file_id="video_sticker_file_id",
            file_size=1000,
        )
    )

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "video_sticker_file_id"
    assert media_type == "video"


def test_get_media_from_message_static_sticker():
    msg = _media_message(
        sticker=MagicMock(
            spec=Sticker,
            is_animated=False,
            is_video=False,
            file_id="static_sticker_file_id",
            file_size=1000,
        )
    )

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "static_sticker_file_id"
    assert media_type == "image"


def test_get_media_from_message_video_with_thumbs():
    thumb = MagicMock(spec=Thumbnail, file_id="thumb_file_id")
    video = MagicMock(spec=Video, file_size=10_000_000, thumbs=[thumb])
    msg = _media_message(video=video)

    file_id, media_type = antinsfw.get_media_from_message(msg)
    assert file_id == "thumb_file_id"
    assert media_type == "image"


async def test_prepare_scan_file_valid_image():
    client = AsyncMock()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_img = Path(temp_dir) / "test.png"
        Image.new("RGB", (50, 50)).save(test_img)
        client.download_media.return_value = test_img

        msg = _media_message(
            photo=MagicMock(spec=Photo, file_size=500, file_id="photo_123")
        )

        scannable = await antinsfw.prepare_scan_file(client, msg, temp_dir)
        assert scannable == str(test_img)


async def test_detect_nsfw_ignores_animated_sticker():
    client = AsyncMock()
    msg = _media_message(spec=None, sticker=MagicMock(is_animated=True))
    msg.chat.id = NSFW_CHAT_ID
    msg.from_user.id = 999

    with patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True):
        await antinsfw.detect_nsfw(client, msg)

    # Must not send any message to chat
    client.download_media.assert_not_called()
    msg.reply_text.assert_not_called()


async def test_nsfwscan_command_animated_sticker_friendly_message():
    client = AsyncMock()
    msg = MagicMock(spec=Message)
    msg.reply_to_message = _media_message(
        sticker=MagicMock(spec=Sticker, is_animated=True)
    )

    msg.reply_text = AsyncMock()

    await antinsfw.nsfw_scan_command(client, msg)

    msg.reply_text.assert_called_once()
    assert (
        "Animated stickers (.tgs) are vector animations"
        in msg.reply_text.call_args[0][0]
    )


async def test_detect_nsfw_deletes_and_notifies_even_for_dev_user():
    client = AsyncMock()
    msg = _nsfw_message(user_id=123456, mention="@owner")  # Even if dev/owner

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True),
        patch("Mikobot.plugins.antinsfw.prepare_scan_file", return_value=SCAN_PATH),
        patch("Mikobot.plugins.antinsfw._scan", return_value=NSFW_PREDICTION),
    ):
        await antinsfw.detect_nsfw(client, msg)

    msg.delete.assert_called_once()
    client.send_message.assert_called_once()
    assert (
        "NSFW Image Detected & Deleted Successfully"
        in client.send_message.call_args[1]["text"]
    )


async def test_detect_nsfw_warns_when_bot_cannot_delete():
    client = AsyncMock()
    msg = _nsfw_message()
    msg.delete.side_effect = Exception("ChatAdminRequired")

    with (
        patch("Database.sql.toggle_sql.is_nsfw_on", return_value=True),
        patch("Mikobot.plugins.antinsfw.prepare_scan_file", return_value=SCAN_PATH),
        patch("Mikobot.plugins.antinsfw._scan", return_value=NSFW_PREDICTION),
    ):
        await antinsfw.detect_nsfw(client, msg)

    msg.delete.assert_called_once()
    client.send_message.assert_called_once()
    assert "Could not delete message" in client.send_message.call_args[1]["text"]


async def test_nsfw_enable_disable_status_query():
    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = NSFW_CHAT_ID
    msg.command = ["antinsfw"]
    msg.reply_text = AsyncMock()

    with patch("Database.sql.toggle_sql.is_nsfw_on", return_value=False):
        await antinsfw.nsfw_enable_disable.__wrapped__(client, msg)

    msg.reply_text.assert_called_once()
    assert "AntiNSFW is currently **disabled**" in msg.reply_text.call_args[0][0]


async def test_nsfw_enable_disable_warns_when_bot_lacks_delete_rights():
    from pyrogram.enums import ChatMemberStatus

    client = AsyncMock()
    msg = MagicMock()
    msg.chat.id = NSFW_CHAT_ID
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

    mock_on.assert_called_once_with(NSFW_CHAT_ID)
    msg.reply_text.assert_called_once()
    assert "Warning" in msg.reply_text.call_args[0][0]
    assert "permission to delete messages" in msg.reply_text.call_args[0][0]


async def test_prepare_scan_file_in_memory_fast_path():
    import io

    client = AsyncMock()
    fake_bio = io.BytesIO(b"fake_image_bytes")
    client.download_media.return_value = fake_bio

    msg = _media_message(
        spec=None,
        photo=MagicMock(file_size=500, file_id="photo_in_mem_123", thumbs=None),
    )

    result = await antinsfw.prepare_scan_file(client, msg)

    client.download_media.assert_called_once_with("photo_in_mem_123", in_memory=True)
    assert result is fake_bio


async def test_lru_cache_deduplicates_media_scans():
    client = AsyncMock()
    msg = _nsfw_message(
        user_id=555, photo_id="repeat_photo_id", unique_id="unique_hash_999"
    )

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
