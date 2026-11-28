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
from pyrogram.enums import ButtonStyle
from pyrogram.errors import BadRequest, PeerIdInvalid, StickersetInvalid
from pyrogram.raw.functions.messages import GetStickerSet, SendMedia
from pyrogram.raw.functions.stickers import (
    AddStickerToSet,
    CreateStickerSet,
)
from pyrogram.raw.types import (
    DocumentAttributeFilename,
    InputDocument,
    InputMediaUploadedDocument,
    InputStickerSetItem,
    InputStickerSetShortName,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.types import InlineKeyboardButton as IKB
from pyrogram.types import InlineKeyboardMarkup as IKM

from Mikobot import MESSAGE_DUMP, app
from Mikobot.logger import LOGGER
from Mikobot.state import state
from Mikobot.utils.cmdprefix import PREFIX_HANDLER
from Mikobot.utils.localization import use_chat_lang


def get_emoji_regex():
    e_list = [
        value.encode("unicode-escape").decode("ASCII")
        for value in emoji.EMOJI_DATA
        if value and not value.startswith("*")
    ]
    # Exclude entries starting with '*' to avoid re.error.
    e_sort = sorted(e_list, reverse=True)
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
        return await ctx.reply("Only stickers are supported.")
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
            f"<b>Sent by:</b> @{self.me.username}",
        )


@app.on_message(filters.command("getvidsticker"), group=222)
async def _vidstick(_, message):
    chat_id = message.chat.id
    replied = message.reply_to_message
    if replied and replied.sticker:
        if not replied.sticker.is_video:
            return await message.reply_text(
                "Use /getsticker if the sticker is not a video."
            )
        file_id = replied.sticker.file_id
        with tempfile.TemporaryDirectory(prefix="yae-vidstick-") as tempdir:
            dest = os.path.join(tempdir, "sticker.mp4")
            new_file = await _.download_media(file_id, file_name=dest)
            await _.send_animation(chat_id, new_file)
    else:
        await message.reply_text("Please reply to a video sticker to upload its MP4.")


@app.on_message(filters.command("getvideo"), group=333)
async def _getvideo(_, message):
    chat_id = message.chat.id
    replied = message.reply_to_message
    if replied and replied.animation:
        file_id = replied.animation.file_id
        with tempfile.TemporaryDirectory(prefix="yae-getvideo-") as tempdir:
            dest = os.path.join(tempdir, "video.mp4")
            new_file = await _.download_media(file_id, file_name=dest)
            await _.send_video(chat_id, video=new_file)
    else:
        await message.reply_text("Reply to a GIF to get its video.")


@app.on_message(filters.command("stickerid", PREFIX_HANDLER) & filters.reply, group=444)
async def getstickerid(_, ctx: Message):
    if ctx.reply_to_message.sticker:
        await ctx.reply(
            "Sticker ID: <code>{stickerid}</code>".format(
                stickerid=ctx.reply_to_message.sticker.file_id
            )
        )


@app.on_message(filters.command("unkang", PREFIX_HANDLER) & filters.reply, group=555)
@use_chat_lang()
async def unkangs(self: Client, ctx: Message, strings):
    if not ctx.from_user:
        return await ctx.reply(
            "Use this command in a private chat to remove a sticker."
        )
    if sticker := ctx.reply_to_message.sticker:
        if str(ctx.from_user.id) not in sticker.set_name:
            return await ctx.reply("This sticker is not from your pack.")
        pp = await ctx.reply(strings("unkang_msg"))
        try:
            await app.delete_sticker_from_set(sticker.file_id)
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

    with tempfile.TemporaryDirectory(prefix="yae-kang-") as temp_dir:
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
                mime = reply.document.mime_type or ""
                if "image" in mime:
                    # mime_type: image/webp
                    resize = True
                elif mime.startswith("video/") or mime in (
                    enums.MessageMediaType.VIDEO,
                    enums.MessageMediaType.ANIMATION,
                ):
                    videos = True
                    convert = True
                elif "tgsticker" in mime:
                    animated = True
            elif reply.sticker:
                if reply.sticker.emoji:
                    sticker_emoji = reply.sticker.emoji
                name = reply.sticker.file_name or ""
                animated = reply.sticker.is_animated
                videos = reply.sticker.is_video
                if videos:
                    convert = False
                elif not animated and not name.endswith(".tgs"):
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
                # A trailing number selects which pack to kang into.
                packnum = ctx.command.pop(1)
                packname = (
                    f"{pack_prefix}{packnum}_{ctx.from_user.id}_by_{self.me.username}"
                )
            if len(ctx.command) > 1:
                sticker_emoji = (
                    "".join(set(EMOJI_PATTERN.findall("".join(ctx.command[1:]))))
                    or sticker_emoji
                )
            filename = await self.download_media(
                ctx.reply_to_message, file_name=temp_dir + os.sep
            )
            if not filename:
                await prog_msg.delete()
                return
        elif ctx.entities and len(ctx.entities) > 1:
            pack_prefix = "a"
            filename = os.path.join(temp_dir, "sticker.png")
            packname = f"c{ctx.from_user.id}_by_{self.me.username}"
            img_url = next(
                (
                    ctx.text[y.offset : (y.offset + y.length)]
                    for y in ctx.entities
                    if y.type in (enums.MessageEntityType.URL, "url")
                ),
                None,
            )

            if not img_url:
                await prog_msg.delete()
                return
            try:
                r = await state.get(img_url, timeout=15)
                if r.status_code == 200:
                    await asyncio.to_thread(Path(filename).write_bytes, r.read())
            except Exception as r_e:
                return await prog_msg.edit(f"{r_e.__class__.__name__} : {r_e}")
            if len(ctx.command) > 2:
                # ctx.command[1] is the image URL.
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
                filename = await asyncio.to_thread(resize_image, filename)
            elif convert:
                filename = await convert_video(filename)
                if filename is False:
                    return await prog_msg.edit("An error occurred.")
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
                        )
                    )
                except PeerIdInvalid:
                    return await prog_msg.edit(
                        strings("please_start_msg"),
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=strings("click_me"),
                                        url=f"https://t.me/{self.me.username}?start",
                                        style=ButtonStyle.PRIMARY,
                                    )
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
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=strings("viewpack"),
                            url=f"https://t.me/addstickers/{packname}",
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            )
            await prog_msg.edit(
                strings("kang_success").format(emot=sticker_emoji),
                reply_markup=markup,
            )
            await self.delete_messages(
                chat_id=MESSAGE_DUMP, message_ids=msg_.id, revoke=True
            )


def resize_image(filename: str) -> str:
    maxsize = 512
    with Image.open(filename) as source:
        scale = min(1, maxsize / max(source.size))
        size = tuple(max(1, round(value * scale)) for value in source.size)
        image = source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        png_image = str(Path(filename).with_suffix(".png"))
        image.save(png_image, "PNG")
    if png_image != filename:
        os.remove(filename)
    return png_image


async def convert_video(filename: str) -> str:
    webm_video = str(Path(filename).with_suffix(".webm"))
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
        await message.reply_text("Reply to an image or a sticker to add text.")
        return

    reply_message = message.reply_to_message
    if not reply_message.media:
        await message.reply_text("Provide some text.")
        return

    text = " ".join(message.command[1:]).strip()
    if not text:
        return await message.reply_text("Use `/mmf text`.")

    if (
        reply_message.document
        and reply_message.document.file_size
        and reply_message.document.file_size > MAX_MEDIA_SIZE
    ):
        return await message.reply_text("That document is too large.")
    if (
        reply_message.photo
        and reply_message.photo.file_size
        and reply_message.photo.file_size > MAX_MEDIA_SIZE
    ):
        return await message.reply_text("That photo is too large.")
    if (
        reply_message.video
        and reply_message.video.file_size
        and reply_message.video.file_size > MAX_MEDIA_SIZE
    ):
        return await message.reply_text("That video is too large.")
    with tempfile.TemporaryDirectory(prefix="yae-memify-") as temp_dir:
        source = os.path.join(
            temp_dir,
            f"{uuid.uuid4().hex}{Path(reply_message.file_name or '').suffix or '.png'}",
        )
        output = os.path.join(temp_dir, f"{uuid.uuid4().hex}.webp")
        downloaded = await client.download_media(reply_message, file_name=source)
        if not downloaded:
            return await message.reply_text("Unable to download that media.")
        meme = await draw_text(downloaded, text, output)
        try:
            await client.send_document(message.chat.id, document=meme)
        finally:
            if os.path.exists(meme):
                os.remove(meme)


def _sync_draw_text(image_path, text, output_path=None):
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


async def draw_text(image_path, text, output_path=None):
    return await asyncio.to_thread(_sync_draw_text, image_path, text, output_path)


@app.on_message(filters.command(["stickerinfo", "stinfo"]), group=888)
async def give_st_info(c: app, m: Message):
    if not m.reply_to_message or not m.reply_to_message.sticker:
        await m.reply_text("Reply to a sticker.")
        return
    st_in = m.reply_to_message.sticker
    st_type = "Normal"
    if st_in.is_animated:
        st_type = "Animated"
    elif st_in.is_video:
        st_type = "Video"
    st_to_gib = f"""[Sticker]({m.reply_to_message.link}) info:
File ID: `{st_in.file_id}`
File name: {st_in.file_name}
File unique ID: `{st_in.file_unique_id}`
Created: `{st_in.date}`
Sticker type: `{st_type}`
Emoji: {st_in.emoji}
Pack name: {st_in.set_name}
"""
    kb = IKM(
        [
            [
                IKB(
                    "Add sticker pack",
                    url=f"https://t.me/addstickers/{st_in.set_name}",
                    style=ButtonStyle.PRIMARY,
                )
            ]
        ]
    )
    await m.reply_text(st_to_gib, reply_markup=kb)
    return


__help__ = """
User commands:
/kang <emoji> or /steal <emoji>: Reply to a sticker or supported media to add it to your pack.
/pkang: Reply to a static sticker to get its full pack.
/stickerinfo or /stinfo: Reply to a sticker to see its details.
/stickerid: Reply to a sticker to see its ID and emoji.
/stickers <query>: Search for sticker packs.
/getsticker: Reply to a sticker to get it as a document.
/getvidsticker: Reply to a video sticker to get its MP4.
/getvideo: Reply to a GIF to get its video.
/unkang: Reply to a sticker added by the bot to remove it from your pack.
/mmf <text>: Reply to a sticker, photo, or video to add text. Use ; to split text between the top and bottom.
Example:
/mmf Hello: Add text at the top.
/mmf Hello ; friends: Add Hello at the top and friends at the bottom.
/mmf ; Hello: Add text at the bottom.
/mmf and /getsticker support only photos and static stickers.
"""

__mod_name__ = "Stickers"
