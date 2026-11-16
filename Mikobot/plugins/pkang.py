from uuid import uuid4

import pyrogram
from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
    stickers = await app.invoke(
        pyrogram.raw.functions.messages.GetStickerSet(
            stickerset=pyrogram.raw.types.InputStickerSetShortName(
                short_name=short_name
            ),
            hash=0,
        )
    )
    shits = stickers.documents
    sticks = []

    for i in shits:
        sex = pyrogram.raw.types.InputDocument(
            id=i.id, access_hash=i.access_hash, file_reference=i.file_reference
        )

        # The emoji lives on the sticker attribute, whose position among the
        # document attributes is not fixed, so it has to be looked up.
        emoji = next(
            (
                attribute.alt
                for attribute in i.attributes
                if isinstance(attribute, pyrogram.raw.types.DocumentAttributeSticker)
            ),
            "",
        )

        sticks.append(pyrogram.raw.types.InputStickerSetItem(document=sex, emoji=emoji))

    try:
        short_name = f"stikcer_pack_{str(uuid4()).replace('-', '')}_by_{bot_username}"
        user_id = await app.resolve_peer(message.from_user.id)
        await app.invoke(
            pyrogram.raw.functions.stickers.CreateStickerSet(
                user_id=user_id,
                title=pack_name,
                short_name=short_name,
                stickers=sticks,
            )
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
