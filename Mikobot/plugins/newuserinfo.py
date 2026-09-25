import os
import tempfile
import uuid

import unidecode
from PIL import Image, ImageChops, ImageDraw, ImageFont
from pyrogram import filters
from pyrogram.enums import ParseMode

from Mikobot import DEMONS, DEV_USERS, DRAGONS, LOGGER, OWNER_ID, TIGERS, WOLVES, app


async def circle(pfp, size=(900, 900)):
    pfp = pfp.resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    bigsize = (pfp.size[0] * 3, pfp.size[1] * 3)
    mask = Image.new("L", bigsize, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + bigsize, fill=255)
    mask = mask.resize(pfp.size, Image.Resampling.LANCZOS)
    mask = ImageChops.darker(mask, pfp.split()[-1])
    pfp.putalpha(mask)
    return pfp


async def download_and_process_pfp(user, source_path):
    try:
        pic = await app.download_media(user.photo.big_file_id, file_name=source_path)
        if pic:
            with Image.open(pic) as source:
                return await circle(source.convert("RGBA"), size=(900, 900))
    except Exception:
        LOGGER.exception("User info operation failed")
    return None


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
    with tempfile.NamedTemporaryFile(prefix="yae-userinfo-", suffix=".png") as source_file:
        source_path = source_path or source_file.name
        user_name = unidecode.unidecode(user.first_name)

        with Image.open("Extra/user.jpg") as source:
            background = source.convert("RGB")
        draw = ImageDraw.Draw(background)
        font = ImageFont.truetype("Extra/default.ttf", 100)

        try:
            pfp = await download_and_process_pfp(user, source_path)
            if pfp:
                pfp_x = 927 + pfp_x_offset
                pfp_y = (background.size[1] - pfp.size[1]) // 2 - 290 + pfp_y_offset
                pfp = await circle(pfp, size=pfp_size)
                background.paste(pfp, (pfp_x, pfp_y), pfp)

            draw.text((user_x, user_y), user_name, font=font, fill="white")
            draw.text((user_id_x, user_id_y), str(user.id), font=font, fill="white")
            userinfo = output_path or f"downloads/userinfo_{user.id}_{uuid.uuid4().hex}.png"
            background.save(userinfo)
            return userinfo
        except Exception:
            LOGGER.exception("User info operation failed")
            return None
        finally:
            background.close()


# Command handler for /userinfo
@app.on_message(filters.command("uinfo"))
async def userinfo_command(client, message):
    user = message.from_user
    user_x, user_y = 1035, 2885
    user_id_x, user_id_y = 1035, 2755

    processing_message = await message.reply("Processing user information...")
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
                f"「 **According to the Mikos analogy, the userinfo is...** : 」\n\n"
                f"❐  𝗜𝗗: {user.id}\n"
                f"❐  𝗙𝗶𝗿𝘀𝘁 𝗡𝗮𝗺𝗲: {user.first_name}\n"
                f"❐  𝗟𝗮𝘀𝘁 𝗡𝗮𝗺𝗲: {user.last_name}\n"
                f"❐  𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲: {user.username}\n"
                f"❐  𝗨𝘀𝗲𝗿𝗹𝗶𝗻𝗸: [link](https://t.me/{user.username})\n"
            )

            # Check if the user's ID matches one of the predefined ranks
            if user.id == OWNER_ID:
                caption += "\n\n〄 The disaster level of this user is **Owner**.\n"
            elif user.id in DEV_USERS:
                caption += "\n\n〄 This user is a member of **Developer**.\n"
            elif user.id in DRAGONS:
                caption += "\n\n〄 The disaster level of this user is **Sudo**.\n"
            elif user.id in DEMONS:
                caption += "\n\n〄 The disaster level of this user is **Demon**.\n"
            elif user.id in TIGERS:
                caption += "\n\n〄 The disaster level of this user is **Tiger**.\n"
            elif user.id in WOLVES:
                caption += "\n\n〄 The disaster level of this user is **Wolf**.\n"

            # Add the RANK line only if the user's ID matches one of the predefined ranks
            if (
                user.id == OWNER_ID
                or user.id in DEV_USERS
                or user.id in DRAGONS
                or user.id in DEMONS
                or user.id in TIGERS
                or user.id in WOLVES
            ):
                caption += "\n\n〄 𝗥𝗮𝗻𝗸: "

                if user.id == OWNER_ID:
                    caption += "**CREATOR**"
                elif user.id in DEV_USERS:
                    caption += "**DEVELOPER**"
                elif user.id in DRAGONS:
                    caption += "**DRAGON**"
                elif user.id in DEMONS:
                    caption += "**DEMON**"
                elif user.id in TIGERS:
                    caption += "**TIGER**"
                elif user.id in WOLVES:
                    caption += "**WOLF**"

                caption += "\n"

            await message.reply_photo(
                photo=image_path, caption=caption, parse_mode=ParseMode.MARKDOWN
            )
            await processing_message.delete()
    except Exception:
        LOGGER.exception("User info operation failed")
