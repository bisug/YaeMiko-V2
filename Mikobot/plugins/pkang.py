from uuid import uuid4

from pyrogram import filters
from pyrogram.enums import ButtonStyle, StickerFormat
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputSticker,
)

from Mikobot import app


@app.on_message(filters.command("pkang"))
async def _packkang(app, message):
    """
    Thanks to @MaybeSuraj on Telegram, who helped build this module.
    """
    txt = await message.reply_text("Processing....")
    if not message.from_user:
        await txt.edit("This command can only be used by users.")
        return
    if not message.reply_to_message:
        await txt.edit("Reply to message")
        return
    if not message.reply_to_message.sticker:
        await txt.edit("Reply to sticker")
        return
    if (
        message.reply_to_message.sticker.is_animated
        or message.reply_to_message.sticker.is_video
    ):
        return await txt.edit("Reply to a non-animated sticker")
    bot_username = (
        getattr(app.me, "username", "bot") if getattr(app, "me", None) else "bot"
    )
    if len(message.command) < 2:
        pack_name = f"{message.from_user.first_name}_sticker_pack_by_@{bot_username}"
    else:
        pack_name = message.text.split(maxsplit=1)[1]
    short_name = message.reply_to_message.sticker.set_name
    sticker_set = await app.get_sticker_set(short_name)
    sticks = [
        InputSticker(
            sticker=sticker.file_id,
            format=StickerFormat.STATIC,
            emoji_list=[sticker.emoji],
        )
        for sticker in sticker_set.stickers
    ]

    try:
        short_name = f"stikcer_pack_{uuid4().hex}_by_{bot_username}"
        await app.create_new_sticker_set(
            user_id=message.from_user.id,
            title=pack_name,
            name=short_name,
            stickers=sticks,
        )
        await txt.edit(
            f"""Sticker added. Remove and re-add your pack to see it sooner.

Total stickers: {len(sticks)}""",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="PACK",
                            url=f"http://t.me/addstickers/{short_name}",
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            ),
        )
    except Exception as e:
        await message.reply_text(str(e))
