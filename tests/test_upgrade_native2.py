"""Focused regressions for sticker/download native replacements."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pyrogram
from PIL import Image

import Mikobot.__main__ as main
from Mikobot.plugins import pkang, stickers, telegraph

STRINGS = lambda key: key  # noqa: E731 - locale strings are not under test

async def test_idle_delegates_to_library_idle(monkeypatch):
    idle = AsyncMock()
    monkeypatch.setattr(pyrogram, "idle", idle)

    await asyncio.wait_for(main._idle(), 0.1)

    idle.assert_awaited_once()


async def test_pkang_uses_high_level_sticker_methods():
    app = MagicMock()
    app.me.username = "bot"
    app.get_sticker_set = AsyncMock()
    set_info = MagicMock()
    set_info.stickers = [MagicMock(file_id="file-id", emoji="😀")]
    app.get_sticker_set.return_value = set_info
    app.create_new_sticker_set = AsyncMock()
    app.invoke = AsyncMock()

    reply = MagicMock()
    reply.sticker.is_animated = False
    reply.sticker.is_video = False
    reply.sticker.set_name = "old_pack"
    message = MagicMock()
    message.command = ["pkang"]
    message.reply_to_message = reply
    message.from_user.id = 1
    message.from_user.first_name = "User"
    txt = MagicMock()
    txt.edit = AsyncMock()
    message.reply_text = AsyncMock(return_value=txt)

    await pkang._packkang(app, message)

    app.get_sticker_set.assert_awaited_once_with("old_pack")
    app.create_new_sticker_set.assert_awaited_once()
    app.invoke.assert_not_awaited()


async def test_unkang_uses_delete_sticker_from_set(monkeypatch):
    client = MagicMock()
    client.delete_sticker_from_set = AsyncMock()
    monkeypatch.setattr(stickers, "app", client)
    ctx = MagicMock()
    ctx.from_user.id = 5
    ctx.reply_to_message.sticker.set_name = "pack_5_by_bot"
    ctx.reply_to_message.sticker.file_id = "file-id"
    pp = MagicMock()
    pp.edit = AsyncMock()
    ctx.reply = AsyncMock(return_value=pp)

    await stickers.unkangs.__wrapped__(client, ctx, STRINGS)

    client.delete_sticker_from_set.assert_awaited_once_with("file-id")


async def test_telegraph_accepts_none_file_size():
    message = MagicMock()
    message.reply_to_message.media.file_size = None
    message.reply_text = AsyncMock()

    await telegraph.telegraph_upload(MagicMock(), message)

    message.reply_text.assert_awaited_once()


async def _write_png(*args, **kwargs):
    target = Path(kwargs["file_name"]) / "sticker.webp"
    Image.new("RGBA", (64, 64)).save(target, "WEBP")
    return str(target)


async def _kang_with_media(media):
    client = MagicMock()
    client.me.username = "bot"
    client.download_media = AsyncMock(side_effect=_write_png)
    client.resolve_peer = AsyncMock()
    ctx = MagicMock()
    ctx.from_user.id = 1
    ctx.from_user.first_name = "User"
    ctx.command = ["kang"]
    ctx.entities = None
    ctx.reply_to_message.media = MagicMock()
    for name in ("photo", "animation", "video", "sticker", "document"):
        setattr(ctx.reply_to_message, name, None)
    for name, value in media.items():
        setattr(ctx.reply_to_message, name, value)
    prog = MagicMock()
    prog.edit = AsyncMock()
    ctx.reply = AsyncMock(return_value=prog)
    await stickers.kang_sticker.__wrapped__(client, ctx, STRINGS)
    return client, prog


async def test_kang_unnamed_sticker_reaches_download():
    client, prog = await _kang_with_media(
        {
            "sticker": MagicMock(
                file_name=None, emoji="✔️", is_animated=False, is_video=False
            )
        }
    )
    client.download_media.assert_awaited_once()
    assert all("no name" not in str(call) for call in prog.edit.await_args_list)


async def test_kang_document_with_none_mime_reaches_download():
    client, _ = await _kang_with_media({"document": MagicMock(mime_type=None)})
    client.download_media.assert_awaited_once()
