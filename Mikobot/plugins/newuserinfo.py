import asyncio
import os
import tempfile
import uuid

import unidecode
from PIL import Image, ImageChops, ImageDraw, ImageFont
from pyrogram import filters
from pyrogram.enums import ParseMode

from Mikobot import DEMONS, DEV_USERS, DRAGONS, OWNER_ID, TIGERS, WOLVES, app
from Mikobot.logger import LOGGER


def _sync_circle(pfp, size=(900, 900)):
    pfp = pfp.resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    bigsize = (pfp.size[0] * 3, pfp.size[1] * 3)
    mask = Image.new("L", bigsize, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + bigsize, fill=255)
    mask = mask.resize(pfp.size, Image.Resampling.LANCZOS)
    mask = ImageChops.darker(mask, pfp.split()[-1])
    pfp.putalpha(mask)
    return pfp


async def circle(pfp, size=(900, 900)):
    return await asyncio.to_thread(_sync_circle, pfp, size)


def _sync_process_pfp(pic):
    with Image.open(pic) as source:
        return _sync_circle(source.convert("RGBA"), size=(900, 900))


async def download_and_process_pfp(user, source_path):
    try:
        pic = await app.download_media(user.photo.big_file_id, file_name=source_path)
        if pic:
            return await asyncio.to_thread(_sync_process_pfp, pic)
    except Exception:
        LOGGER.exception("User info operation failed")
    return None


def _sync_build_userinfopic(
    user_name,
    user_id,
    pfp,
    user_x,
    user_y,
    user_id_x,
    user_id_y,
    pfp_x_offset=0,
    pfp_y_offset=0,
    pfp_size=(1218, 1385),
    output_path=None,
):
    with Image.open("Extra/user.jpg") as source:
        background = source.convert("RGB")
    draw = ImageDraw.Draw(background)
    font = ImageFont.truetype("Extra/default.ttf", 100)

    if pfp:
        pfp_x = 927 + pfp_x_offset
        pfp_y = (background.size[1] - pfp.size[1]) // 2 - 290 + pfp_y_offset
        pfp = _sync_circle(pfp, size=pfp_size)
        background.paste(pfp, (pfp_x, pfp_y), pfp)

    draw.text((user_x, user_y), user_name, font=font, fill="white")
    draw.text((user_id_x, user_id_y), str(user_id), font=font, fill="white")
    userinfo = output_path or f"downloads/userinfo_{user_id}_{uuid.uuid4().hex}.png"
    background.save(userinfo)
    return userinfo


async def userinfopic(
    user,
    user_x,
    user_y,
    user_id_x,
    user_id_y,
    pfp_x_offset=0,
    pfp_y_offset=0,
    pfp_size=(1218, 1385),
    source_path=None,
    output_path=None,
):
    with tempfile.NamedTemporaryFile(
        prefix="yae-userinfo-", suffix=".png"
    ) as source_file:
        source_path = source_path or source_file.name
        user_name = unidecode.unidecode(user.first_name)

        try:
            pfp = await download_and_process_pfp(user, source_path)
            return await asyncio.to_thread(
                _sync_build_userinfopic,
                user_name,
                user.id,
                pfp,
                user_x,
                user_y,
                user_id_x,
                user_id_y,
                pfp_x_offset,
                pfp_y_offset,
                pfp_size,
                output_path,
            )
        except Exception:
            LOGGER.exception("User info operation failed")
            return None


@app.on_message(filters.command("uinfo"))
async def userinfo_command(client, message):
    user = message.from_user
    if not user:
        return await message.reply_text("Only users can check user info.")
    user_x, user_y = 1035, 2885
    user_id_x, user_id_y = 1035, 2755

    processing_message = await message.reply_text("Processing user information.")
    try:
        with tempfile.TemporaryDirectory(prefix="yae-userinfo-") as temp_dir:
            image_path = await userinfopic(
                user,
                user_x,
                user_y,
                user_id_x,
                user_id_y,
                source_path=os.path.join(temp_dir, f"{user.id}.png"),
                output_path=os.path.join(temp_dir, "userinfo.png"),
            )
            if not image_path:
                await processing_message.delete()
                return
            caption = (
                f"**User information**\n\n"
                f"ID: {user.id}\n"
                f"First name: {user.first_name}\n"
                f"Last name: {user.last_name}\n"
                f"Username: {user.username}\n"
                f"User link: [link](https://t.me/{user.username})\n"
            )

            if user.id == OWNER_ID:
                caption += "\n\nRole: **Owner**.\n"
            elif user.id in DEV_USERS:
                caption += "\n\nRole: **Developer**.\n"
            elif user.id in DRAGONS:
                caption += "\n\nRole: **Sudo**.\n"
            elif user.id in DEMONS:
                caption += "\n\nRole: **Demon**.\n"
            elif user.id in TIGERS:
                caption += "\n\nRole: **Tiger**.\n"
            elif user.id in WOLVES:
                caption += "\n\nRole: **Wolf**.\n"

            if (
                user.id == OWNER_ID
                or user.id in DEV_USERS
                or user.id in DRAGONS
                or user.id in DEMONS
                or user.id in TIGERS
                or user.id in WOLVES
            ):
                caption += "\n\nRank: "

                if user.id == OWNER_ID:
                    caption += "**Creator**"
                elif user.id in DEV_USERS:
                    caption += "**Developer**"
                elif user.id in DRAGONS:
                    caption += "**Dragon**"
                elif user.id in DEMONS:
                    caption += "**Demon**"
                elif user.id in TIGERS:
                    caption += "**Tiger**"
                elif user.id in WOLVES:
                    caption += "**Wolf**"

                caption += "\n"

            await message.reply_photo(
                photo=image_path, caption=caption, parse_mode=ParseMode.MARKDOWN
            )
            await processing_message.delete()
    except Exception:
        LOGGER.exception("User info operation failed")
