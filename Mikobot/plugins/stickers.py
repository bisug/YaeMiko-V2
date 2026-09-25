import asyncio
import os
import re
import tempfile
import textwrap
import uuid
from pathlib import Path

import emoji
from PIL import Image, ImageDraw, ImageFont
from pyrogram import Client, enums, filters
from pyrogram.errors import BadRequest, PeerIdInvalid, StickersetInvalid
from pyrogram.file_id import FileId
from pyrogram.raw.functions.messages import GetStickerSet, SendMedia
from pyrogram.raw.functions.stickers import (
    AddStickerToSet,
    CreateStickerSet,
    RemoveStickerFromSet,
)
from pyrogram.raw.types import (
    DocumentAttributeFilename,
    InputDocument,
    InputMediaUploadedDocument,
    InputStickerSetItem,
    InputStickerSetShortName,
)
from pyrogram.types import InlineKeyboardButton
from pyrogram.types import InlineKeyboardButton as IKB
from pyrogram.types import InlineKeyboardMarkup
from pyrogram.types import InlineKeyboardMarkup as IKM
from pyrogram.types import Message

from Mikobot import LOGGER, MESSAGE_DUMP, app
from Mikobot.state import state
from Mikobot.utils.custom_filters import PREFIX_HANDLER
from Mikobot.utils.localization import use_chat_lang
from pyrogram.enums import ButtonStyle


def get_emoji_regex():
    e_list = [
        value.encode("unicode-escape").decode("ASCII")
        for value in emoji.EMOJI_DATA
        if value and not value.startswith("*")
    ]
    # to avoid re.error excluding char that start with '*'
    e_sort = sorted([x for x in e_list if not x.startswith("*")], reverse=True)
    # Sort emojis by length to make sure multi-character emojis are
    # matched first
    pattern_ = f"({'|'.join(e_sort)})"
    return re.compile(pattern_)


EMOJI_PATTERN = get_emoji_regex()
SUPPORTED_TYPES = ["jpeg", "png", "webp"]
MAX_MEDIA_SIZE = 20 * 1024 * 1024


@app.on_message(filters.command(["getsticker"], PREFIX_HANDLER), group=111)
@use_chat_lang()
async def getsticker_(self: Client, ctx: Message, strings):
    if not ctx.reply_to_message:
        return await ctx.reply(strings("not_sticker"))
    sticker = ctx.reply_to_message.sticker
    if not sticker:
        return await ctx.reply("Only support sticker..")
    if sticker.is_animated:
        return await ctx.reply(strings("no_anim_stick"))
    with tempfile.TemporaryDirectory(prefix="yae-sticker-") as tempdir:
        sticker_file = await self.download_media(
            message=ctx.reply_to_message,
            file_name=os.path.join(tempdir, f"{sticker.set_name or 'sticker'}.png"),
        )
        await ctx.reply_to_message.reply_document(
            document=sticker_file,
            caption=f"<b>Emoji:</b> {sticker.emoji}\n"
            f"<b>Sticker ID:</b> <code>{sticker.file_id}</code>\n\n"
            f"<b>Send by:</b> @{self.me.username}",
        )


@app.on_message(filters.command("getvidsticker"), group=222)
async def _vidstick(_, message):
    chat_id = message.chat.id
    replied = message.reply_to_message
    if replied and replied.sticker:
        if not replied.sticker.is_video:
            return await message.reply_text("Use /getsticker if sticker is not video.")
        file_id = replied.sticker.file_id
        new_file = await _.download_media(file_id, file_name="sticker.mp4")
        await _.send_animation(chat_id, new_file)
        os.remove(new_file)
    else:
        await message.reply_text("Please reply to a video sticker to upload it's MP4.")


@app.on_message(filters.command("getvideo"), group=333)
async def _vidstick(_, message):
    chat_id = message.chat.id
    replied = message.reply_to_message
    if replied and replied.animation:
        file_id = replied.animation.file_id
        new_file = await _.download_media(file_id, file_name="video.mp4")
        try:
            await _.send_video(chat_id, video=open(new_file, "rb"))
        finally:
            os.remove(new_file)
    else:
        await message.reply_text("Please reply to a gif for me to get it's video.")


@app.on_message(filters.command("stickerid", PREFIX_HANDLER) & filters.reply, group=444)
async def getstickerid(_, ctx: Message):
    if ctx.reply_to_message.sticker:
        await ctx.reply(
            "The ID of this sticker is: <code>{stickerid}</code>".format(
                stickerid=ctx.reply_to_message.sticker.file_id
            )
        )


@app.on_message(filters.command("unkang", PREFIX_HANDLER) & filters.reply, group=555)
@use_chat_lang()
async def unkangs(self: Client, ctx: Message, strings):
    if not ctx.from_user:
        return await ctx.reply("You're anon, unkang in my PM")
    if sticker := ctx.reply_to_message.sticker:
        if str(ctx.from_user.id) not in sticker.set_name:
            return await ctx.reply("This sticker is not your pack, don't do it..")
        pp = await ctx.reply(strings("unkang_msg"))
        try:
            decoded = FileId.decode(sticker.file_id)
            sticker = InputDocument(
                id=decoded.media_id,
                access_hash=decoded.access_hash,
                file_reference=decoded.file_reference,
            )
            await app.invoke(RemoveStickerFromSet(sticker=sticker))
            await pp.edit(strings("unkang_success"))
        except Exception as e:
            await pp.edit(strings("unkang_error").format(e=e))
    else:
        await ctx.reply(strings("unkang_help").format(c=self.me.username))


@app.on_message(filters.command(["kang"], PREFIX_HANDLER), group=666)
@use_chat_lang()
async def kang_sticker(self: Client, ctx: Message, strings):
    if not ctx.from_user:
        return await ctx.reply(strings("anon_warn"))
    prog_msg = await ctx.reply(strings("kang_msg"))
    sticker_emoji = "✔️"
    packnum = 0
    packname_found = False
    resize = False
    animated = False
    videos = False
    convert = False
    reply = ctx.reply_to_message
    user = await self.resolve_peer(ctx.from_user.username or ctx.from_user.id)

    if reply and reply.media:
        if reply.photo:
            resize = True
        elif reply.animation:
            videos = True
            convert = True
        elif reply.video:
            convert = True
            videos = True
        elif reply.document:
            if "image" in reply.document.mime_type:
                # mime_type: image/webp
                resize = True
            elif reply.document.mime_type in (
                enums.MessageMediaType.VIDEO,
                enums.MessageMediaType.ANIMATION,
            ):
                # mime_type: application/video
                videos = True
                convert = True
            elif "tgsticker" in reply.document.mime_type:
                # mime_type: application/x-tgsticker
                animated = True
        elif reply.sticker:
            if not reply.sticker.file_name:
                return await prog_msg.edit(strings("stick_no_name"))
            if reply.sticker.emoji:
                sticker_emoji = reply.sticker.emoji
            animated = reply.sticker.is_animated
            videos = reply.sticker.is_video
            if videos:
                convert = False
            elif not reply.sticker.file_name.endswith(".tgs"):
                resize = True
        else:
            return await prog_msg.edit("I cannot kang this type.")

        pack_prefix = "anim" if animated else "vid" if videos else "a"
        packname = f"{pack_prefix}_{ctx.from_user.id}_by_{self.me.username}"

        if (
            len(ctx.command) > 1
            and ctx.command[1].isdigit()
            and int(ctx.command[1]) > 0
        ):
            # provide pack number to kang in desired pack
            packnum = ctx.command.pop(1)
            packname = (
                f"{pack_prefix}{packnum}_{ctx.from_user.id}_by_{self.me.username}"
            )
        if len(ctx.command) > 1:
            # matches all valid emojis in input
            sticker_emoji = (
                "".join(set(EMOJI_PATTERN.findall("".join(ctx.command[1:]))))
                or sticker_emoji
            )
        filename = await self.download_media(ctx.reply_to_message)
        if not filename:
            # Failed to download
            await prog_msg.delete()
            return
    elif ctx.entities and len(ctx.entities) > 1:
        pack_prefix = "a"
        filename = "sticker.png"
        packname = f"c{ctx.from_user.id}_by_{self.me.username}"
        img_url = next(
            (
                ctx.text[y.offset : (y.offset + y.length)]
                for y in ctx.entities
                if y.type == "url"
            ),
            None,
        )

        if not img_url:
            await prog_msg.delete()
            return
        try:
            r = await state.get(img_url)
            if r.status_code == 200:
                with open(filename, mode="wb") as f:
                    f.write(r.read())
        except Exception as r_e:
            return await prog_msg.edit(f"{r_e.__class__.__name__} : {r_e}")
        if len(ctx.command) > 2:
            # m.command[1] is image_url
            if ctx.command[2].isdigit() and int(ctx.command[2]) > 0:
                packnum = ctx.command.pop(2)
                packname = f"a{packnum}_{ctx.from_user.id}_by_{self.me.username}"
            if len(ctx.command) > 2:
                sticker_emoji = (
                    "".join(set(EMOJI_PATTERN.findall("".join(ctx.command[2:]))))
                    or sticker_emoji
                )
            resize = True
    else:
        return await prog_msg.edit(strings("kang_help"))
    try:
        if resize:
            filename = resize_image(filename)
        elif convert:
            filename = await convert_video(filename)
            if filename is False:
                return await prog_msg.edit("Error")
        max_stickers = 50 if animated else 120
        while not packname_found:
            try:
                stickerset = await self.invoke(
                    GetStickerSet(
                        stickerset=InputStickerSetShortName(short_name=packname),
                        hash=0,
                    )
                )
                if stickerset.set.count >= max_stickers:
                    packnum += 1
                    packname = f"{pack_prefix}_{packnum}_{ctx.from_user.id}_by_{self.me.username}"
                else:
                    packname_found = True
            except StickersetInvalid:
                break
        file = await self.save_file(filename)
        media = await self.invoke(
            SendMedia(
                peer=(await self.resolve_peer(MESSAGE_DUMP)),
                media=InputMediaUploadedDocument(
                    file=file,
                    mime_type=self.guess_mime_type(filename),
                    attributes=[DocumentAttributeFilename(file_name=filename)],
                ),
                message=f"#Sticker kang by UserID -> {ctx.from_user.id}",
                random_id=self.rnd_id(),
            ),
        )
        msg_ = media.updates[-1].message
        stkr_file = msg_.media.document
        if packname_found:
            await prog_msg.edit(strings("exist_pack"))
            await self.invoke(
                AddStickerToSet(
                    stickerset=InputStickerSetShortName(short_name=packname),
                    sticker=InputStickerSetItem(
                        document=InputDocument(
                            id=stkr_file.id,
                            access_hash=stkr_file.access_hash,
                            file_reference=stkr_file.file_reference,
                        ),
                        emoji=sticker_emoji,
                    ),
                )
            )
        else:
            await prog_msg.edit(strings("new_packs"))
            stkr_title = f"{ctx.from_user.first_name}'s"
            if animated:
                stkr_title += "AnimPack"
            elif videos:
                stkr_title += "VidPack"
            if packnum != 0:
                stkr_title += f" v{packnum}"
            try:
                await self.invoke(
                    CreateStickerSet(
                        user_id=user,
                        title=stkr_title,
                        short_name=packname,
                        stickers=[
                            InputStickerSetItem(
                                document=InputDocument(
                                    id=stkr_file.id,
                                    access_hash=stkr_file.access_hash,
                                    file_reference=stkr_file.file_reference,
                                ),
                                emoji=sticker_emoji,
                            )
                        ],
                        animated=animated,
                        videos=videos,
                    )
                )
            except PeerIdInvalid:
                return await prog_msg.edit(
                    strings("please_start_msg"),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    strings("click_me"),
                                    url=f"https://t.me/{self.me.username}?start",
                                 style=ButtonStyle.PRIMARY)
                            ]
                        ]
                    ),
                )

    except BadRequest:
        return await prog_msg.edit(strings("pack_full"))
    except Exception as all_e:
        await prog_msg.edit(f"{all_e.__class__.__name__} : {all_e}")
    else:
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=strings("viewpack"),
                        url=f"https://t.me/addstickers/{packname}",
                     style=ButtonStyle.PRIMARY)
                ]
            ]
        )
        await prog_msg.edit(
            strings("kang_success").format(emot=sticker_emoji),
            reply_markup=markup,
        )
        # Cleanup
        await self.delete_messages(
            chat_id=MESSAGE_DUMP, message_ids=msg_.id, revoke=True
        )
        try:
            os.remove(filename)
        except OSError:
            pass


def resize_image(filename: str) -> str:
    maxsize = 512
    with Image.open(filename) as source:
        scale = min(1, maxsize / max(source.size))
        size = tuple(max(1, round(value * scale)) for value in source.size)
        image = source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        downpath, _ = os.path.split(filename)
        png_image = os.path.join(
            downpath,
            f"{os.path.splitext(os.path.basename(filename))[0]}.png",
        )
        image.save(png_image, "PNG")
    if png_image != filename:
        os.remove(filename)
    return png_image


async def convert_video(filename: str) -> str:
    downpath, _ = os.path.split(filename)
    webm_video = os.path.join(
        downpath, f"{os.path.splitext(os.path.basename(filename))[0]}.webm"
    )
    cmd = [
        "ffmpeg",
        "-loglevel",
        "quiet",
        "-i",
        filename,
        "-t",
        "00:00:03",
        "-vf",
        "fps=30",
        "-c:v",
        "vp9",
        "-b:v:",
        "500k",
        "-preset",
        "ultrafast",
        "-s",
        "512x512",
        "-y",
        "-an",
        webm_video,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return False
    if proc.returncode != 0 or not os.path.exists(webm_video):
        LOGGER.error("FFmpeg conversion failed: %s", stderr.decode(errors="replace"))
        return False
    if webm_video != filename:
        os.remove(filename)
    return webm_video


@app.on_message(filters.command("mmf"), group=777)
async def handler(client, message):
    if not message.reply_to_message:
        await message.reply("Reply to an image or a sticker to memify it!")
        return

    reply_message = message.reply_to_message
    if not reply_message.media:
        await message.reply("Provide some text please.")
        return

    text = message.text.split("/mmf ", maxsplit=1)[1].strip()
    if not text:
        return await message.reply("You might want to try `/mmf text`")

    if reply_message.document and reply_message.document.file_size and reply_message.document.file_size > MAX_MEDIA_SIZE:
        return await message.reply("That document is too large.")
    if reply_message.photo and reply_message.photo.file_size and reply_message.photo.file_size > MAX_MEDIA_SIZE:
        return await message.reply("That photo is too large.")
    if reply_message.video and reply_message.video.file_size and reply_message.video.file_size > MAX_MEDIA_SIZE:
        return await message.reply("That video is too large.")
    with tempfile.TemporaryDirectory(prefix="yae-memify-") as temp_dir:
        source = os.path.join(temp_dir, f"{uuid.uuid4().hex}{Path(reply_message.file_name or '').suffix or '.png'}")
        output = os.path.join(temp_dir, f"{uuid.uuid4().hex}.webp")
        downloaded = await client.download_media(reply_message, file_name=source)
        if not downloaded:
            return await message.reply("Unable to download that media.")
        meme = await draw_text(downloaded, text, output)
        try:
            await client.send_document(message.chat.id, document=meme)
        finally:
            if os.path.exists(meme):
                os.remove(meme)


async def draw_text(image_path, text, output_path=None):
    with Image.open(image_path) as source:
        img = source.convert("RGBA")
    i_width, i_height = img.size

    if os.name == "nt":
        fnt = "arial.ttf"
    else:
        fnt = "./Extra/default.ttf"
    m_font = ImageFont.truetype(fnt, int((70 / 640) * i_width))

    if ";" in text:
        upper_text, lower_text = text.split(";")
    else:
        upper_text = text
        lower_text = ""

    draw = ImageDraw.Draw(img)
    current_h, pad = 10, 5

    if upper_text:
        for u_text in textwrap.wrap(upper_text, width=15):
            u_bbox = draw.textbbox((0, 0), u_text, font=m_font)
            u_width, u_height = u_bbox[2] - u_bbox[0], u_bbox[3] - u_bbox[1]

            draw.text(
                xy=(((i_width - u_width) / 2) - 2, int((current_h / 640) * i_width)),
                text=u_text,
                font=m_font,
                fill=(0, 0, 0),
            )

            draw.text(
                xy=(((i_width - u_width) / 2) + 2, int((current_h / 640) * i_width)),
                text=u_text,
                font=m_font,
                fill=(0, 0, 0),
            )
            draw.text(
                xy=((i_width - u_width) / 2, int(((current_h / 640) * i_width)) - 2),
                text=u_text,
                font=m_font,
                fill=(0, 0, 0),
            )

            draw.text(
                xy=(((i_width - u_width) / 2), int(((current_h / 640) * i_width)) + 2),
                text=u_text,
                font=m_font,
                fill=(0, 0, 0),
            )

            draw.text(
                xy=((i_width - u_width) / 2, int((current_h / 640) * i_width)),
                text=u_text,
                font=m_font,
                fill=(255, 255, 255),
            )

            current_h += u_height + pad

    if lower_text:
        for l_text in textwrap.wrap(lower_text, width=15):
            l_bbox = draw.textbbox((0, 0), l_text, font=m_font)
            u_width, u_height = l_bbox[2] - l_bbox[0], l_bbox[3] - l_bbox[1]

            draw.text(
                xy=(
                    ((i_width - u_width) / 2) - 2,
                    i_height - u_height - int((20 / 640) * i_width),
                ),
                text=l_text,
                font=m_font,
                fill=(0, 0, 0),
            )
            draw.text(
                xy=(
                    ((i_width - u_width) / 2) + 2,
                    i_height - u_height - int((20 / 640) * i_width),
                ),
                text=l_text,
                font=m_font,
                fill=(0, 0, 0),
            )
            draw.text(
                xy=(
                    (i_width - u_width) / 2,
                    (i_height - u_height - int((20 / 640) * i_width)) - 2,
                ),
                text=l_text,
                font=m_font,
                fill=(0, 0, 0),
            )
            draw.text(
                xy=(
                    (i_width - u_width) / 2,
                    (i_height - u_height - int((20 / 640) * i_width)) + 2,
                ),
                text=l_text,
                font=m_font,
                fill=(0, 0, 0),
            )

            draw.text(
                xy=(
                    (i_width - u_width) / 2,
                    i_height - u_height - int((20 / 640) * i_width),
                ),
                text=l_text,
                font=m_font,
                fill=(255, 255, 255),
            )

            current_h += u_height + pad

    if output_path is None:
        output_path = f"{uuid.uuid4().hex}.webp"
    img.save(output_path, "webp")
    return output_path


@app.on_message(filters.command(["stickerinfo", "stinfo"]), group=888)
async def give_st_info(c: app, m: Message):
    if not m.reply_to_message:
        await m.reply_text("Reply to a sticker")
        return
    elif not m.reply_to_message.sticker:
        await m.reply_text("Reply to a sticker")
        return
    st_in = m.reply_to_message.sticker
    st_type = "Normal"
    if st_in.is_animated:
        st_type = "Animated"
    elif st_in.is_video:
        st_type = "Video"
    st_to_gib = f"""[Sticker]({m.reply_to_message.link}) info:
➼ 𝗙𝗜𝗟𝗘 𝗜𝗗 : `{st_in.file_id}`
➼ 𝗙𝗜𝗟𝗘 𝗡𝗔𝗠𝗘 : {st_in.file_name}
➼ 𝗙𝗜𝗟𝗘 𝗨𝗡𝗜𝗤𝗨𝗘 𝗜𝗗 : `{st_in.file_unique_id}`
➼ 𝗗𝗔𝗧𝗘 𝗔𝗡𝗗 𝗧𝗜𝗠𝗘 𝗢𝗙 𝗦𝗧𝗜𝗖𝗞𝗘𝗥 𝗖𝗥𝗘𝗔𝗧𝗘𝗗 : `{st_in.date}`
➼ 𝗦𝗧𝗜𝗖𝗞𝗘𝗥 𝗧𝗬𝗣𝗘 : `{st_type}`
➼ 𝗘𝗠𝗢𝗝𝗜 : {st_in.emoji}
➼ 𝗣𝗔𝗖𝗞 𝗡𝗔𝗠𝗘 : {st_in.set_name}
"""
    kb = IKM(
        [
            [
                IKB(
                    "➕ 𝗔𝗱𝗱 𝘀𝘁𝗶𝗰𝗸𝗲𝗿 𝗽𝗮𝗰𝗸",
                    url=f"https://t.me/addstickers/{st_in.set_name}",
                 style=ButtonStyle.PRIMARY)
            ]
        ]
    )
    await m.reply_text(st_to_gib, reply_markup=kb)
    return


# <=================================================== HELP ====================================================>
__help__ = """
➠ *👨‍🏫 User Commands:*

» /kang (/steal) < emoji >: Reply to a sticker or any supported media.

» /pkang: Reply to a image type sticker to get full pack.

» /stickerinfo (/stinfo) : Reply to any sticker to get it's info.

» /stickerid Reply to a sticker message to get the sticker ID and emoji.

» /stickers < query >: Search for sticker packs based on the given query.

» /getsticker: Reply to a sticker message to get the sticker as a document.

» /getvidsticker: Reply to a video sticker message to get the video as an animation.

» /getvideo: Reply to a GIF message to get the GIF as a video.

» /unkang: Reply to a sticker created by the bot to remove it from your pack.

» /mmf < your text >: Reply to a normal sticker or a photo or video file to memify it. If you want to right text at bottom use `;right your message`
    ■ For e.g. 
    ○ /mmf Hello freinds : this will add text to the top
    ○ /mmf Hello ; freinds : this will add Hello to the top and freinds at the bottom
    ○ /mmf ; Hello friends : this will add text at the bottom

➠ *Note*
➠ *mmf and getsticker only support photo and normal stickers for now*.
"""

__mod_name__ = "STICKERS"
# <================================================ END =======================================================>
