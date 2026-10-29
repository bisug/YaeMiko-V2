# <============================================== IMPORTS =========================================================>
import base64
import io
import os
import tempfile
from pathlib import Path
from random import choice

import httpx
from PIL import Image
from pyrogram.enums import MessageEntityType


def get_display_name(user):
    if user is None:
        return None
    return " ".join(part for part in (user.first_name, user.last_name) if part) or None


from Mikobot import DEV_USERS, LOGGER, app
from Mikobot.events import register
from Mikobot.plugins.telegraph import _upload
from Mikobot.state import state

# <=======================================================================================================>


# <================================================ CLASS & FUNCTION =======================================================>
class Quotly:
    _API = "https://shnwazdev-quoteapi.vercel.app/quote/generate"

    _COLORS = (
        "#1b1429",
        "#2b1b3d",
        "#123456",
        "#0f2027",
        "#42275a",
        "#2c3e50",
        "#3a1c71",
        "#4b1248",
        "#1f4037",
        "#16222a",
    )
    _entities = {
        MessageEntityType.PHONE_NUMBER: "phone_number",
        MessageEntityType.MENTION: "mention",
        MessageEntityType.BOLD: "bold",
        MessageEntityType.ITALIC: "italic",
        MessageEntityType.CASHTAG: "cashtag",
        MessageEntityType.STRIKETHROUGH: "strikethrough",
        MessageEntityType.HASHTAG: "hashtag",
        MessageEntityType.EMAIL: "email",
        MessageEntityType.TEXT_MENTION: "text_mention",
        MessageEntityType.UNDERLINE: "underline",
        MessageEntityType.URL: "url",
        MessageEntityType.TEXT_LINK: "text_link",
        MessageEntityType.BOT_COMMAND: "bot_command",
        MessageEntityType.CODE: "code",
        MessageEntityType.PRE: "pre",
        MessageEntityType.SPOILER: "spoiler",
        MessageEntityType.CUSTOM_EMOJI: "custom_emoji",
        MessageEntityType.BLOCKQUOTE: "blockquote",
    }

    async def _format_quote(self, event, reply=None, sender=None, type_="private"):
        async def upload_media(file_):
            png_file = f"{file_}.png"
            try:
                with Image.open(file_) as image:
                    converted = image.convert("RGB")
                    converted.save(png_file, "PNG")
                return await _upload(Path(png_file), "catbox")
            finally:
                if os.path.exists(png_file):
                    try:
                        os.remove(png_file)
                    except OSError:
                        pass
                if os.path.exists(file_):
                    try:
                        os.remove(file_)
                    except OSError:
                        pass

        reply_dict = {}
        if reply:
            reply_user = getattr(reply, "from_user", None)
            reply_chat = getattr(reply, "sender_chat", None)
            reply_name = (
                get_display_name(reply_user)
                or (reply_chat.title if reply_chat else None)
                or "Deleted Account"
            )
            reply_id = (
                reply_user.id
                if reply_user
                else (reply_chat.id if reply_chat else reply.chat.id)
            )
            reply_dict = {
                "name": reply_name,
                "text": reply.text or reply.caption or "",
                "chatId": reply_id,
            }

        forward_origin = event.forward_origin
        sender_chat = getattr(event, "sender_chat", None)
        from_user = getattr(event, "from_user", None)
        name, last_name, username = None, None, None

        if sender and sender.id not in DEV_USERS:
            id_ = sender.id
            name = get_display_name(sender)
            last_name = getattr(sender, "last_name", None)
            username = getattr(sender, "username", None)
        elif not forward_origin:
            if from_user:
                id_ = from_user.id
                name = get_display_name(from_user)
                last_name = getattr(from_user, "last_name", None)
                username = getattr(from_user, "username", None)
            elif sender_chat:
                id_ = sender_chat.id
                name = sender_chat.title or "Channel"
                last_name = None
                username = getattr(sender_chat, "username", None)
            else:
                id_ = event.chat.id if hasattr(event, "chat") else 0
                name = "Unknown"
                last_name = None
                username = None
        else:
            sender_user = getattr(forward_origin, "sender_user", None)
            forward_chat = getattr(forward_origin, "sender_chat", None) or getattr(
                forward_origin, "chat", None
            )
            id_ = (
                sender_user.id
                if sender_user
                else (forward_chat.id if forward_chat else None)
            )
            name = (
                get_display_name(sender_user)
                or getattr(forward_origin, "sender_user_name", None)
                or getattr(forward_chat, "title", None)
                or getattr(forward_origin, "author_signature", None)
                or "Unknown"
            )
            last_name = (
                getattr(sender_user, "last_name", None) if sender_user else None
            )
            username = (
                getattr(sender_user, "username", None)
                if sender_user
                else getattr(forward_chat, "username", None)
            )

        raw_entities = getattr(event, "entities", None) or getattr(event, "caption_entities", None) or []
        entities = []
        for entity in raw_entities:
            entity_type = self._entities.get(
                entity.type,
                str(getattr(entity.type, "value", entity.type)).lower(),
            )
            ent = {
                "type": entity_type,
                "offset": entity.offset,
                "length": entity.length,
            }
            if getattr(entity, "url", None):
                ent["url"] = entity.url
            if getattr(entity, "user", None):
                u = entity.user
                ent["user"] = {
                    "id": u.id,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "username": u.username,
                }
            if getattr(entity, "language", None):
                ent["language"] = entity.language
            if getattr(entity, "custom_emoji_id", None):
                ent["custom_emoji_id"] = entity.custom_emoji_id
            entities.append(ent)

        text_content = event.text or event.caption or ""

        message = {
            "entities": entities,
            "chatId": id_,
            "avatar": True,
            "from": {
                "id": id_,
                "first_name": name or "Deleted Account",
                "last_name": last_name,
                "username": username,
                "language_code": "en",
                "title": name,
                "name": name or "Unknown",
                "type": type_,
            },
            "text": text_content,
            "replyMessage": reply_dict,
        }

        media_file = None
        try:
            if getattr(event, "photo", None):
                media_file = await event.download_media()
            elif getattr(event, "sticker", None):
                media_file = await event.download_media()
            elif getattr(event, "document", None) and getattr(event.document, "thumbs", None):
                media_file = await event.download_media(thumb=-1)
            elif getattr(event, "video", None) and getattr(event.video, "thumbs", None):
                media_file = await event.download_media(thumb=-1)
            elif getattr(event, "animation", None) and getattr(event.animation, "thumbs", None):
                media_file = await event.download_media(thumb=-1)
        except Exception as err:
            LOGGER.warning("Failed to download quote media: %s", err)
            media_file = None

        if media_file:
            try:
                uri = await upload_media(media_file)
                if uri:
                    message["media"] = {"url": uri}
            except Exception as err:
                LOGGER.warning("Failed to upload quote media: %s", err)

        return message

    async def create_quotly(
        self,
        event,
        url=None,
        reply=None,
        bg=None,
        sender=None,
        OQAPI=True,
        file_name=None,
    ):
        if not isinstance(event, list):
            event = [event]
        url = url or self._API
        bg = bg or self._COLORS[0]
        content = {
            "type": "quote",
            "format": "webp",
            "backgroundColor": bg,
            "width": 512,
            "height": 768,
            "scale": 2,
            "messages": [
                await self._format_quote(message, reply=reply, sender=sender)
                for message in event
            ],
        }
        try:
            request = await async_searcher(url, post=True, json=content, re_json=True)
        except (ValueError, httpx.HTTPError) as er:
            if url != self._API:
                return await self.create_quotly(self._API)
            raise er

        if isinstance(request, dict) and request.get("ok"):
            image_data = base64.b64decode(request["result"]["image"])
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
                file_name = file.name
                with Image.open(io.BytesIO(image_data)) as image:
                    image.convert("RGB").save(file, format="PNG")
            return file_name
        error_msg = request.get("error", {}).get("message", str(request)) if isinstance(request, dict) else str(request)
        raise RuntimeError(f"Quote API error: {error_msg}")


quotly = Quotly()


async def async_searcher(
    url: str,
    post: bool = None,
    headers: dict = None,
    params: dict = None,
    json: dict = None,
    data: dict = None,
    ssl=None,
    re_json: bool = False,
    re_content: bool = False,
    real: bool = False,
    *args,
    **kwargs,
):
    request = (
        state.post(url, headers=headers, params=params, json=json, data=data, **kwargs)
        if post
        else state.get(url, headers=headers, params=params, **kwargs)
    )
    response = await request
    response.raise_for_status()
    if re_json:
        return response.json()
    if re_content:
        return response.content
    return response.text


@register(pattern=r"^/q(?:@\S+)?(?: |$)(.*)")
async def quott_(event):
    raw_match = ""
    if event.command and len(event.command) > 1:
        raw_match = event.command[1]
    elif getattr(event, "matches", None) and event.matches[0].groups():
        raw_match = event.matches[0].group(1) or ""
    elif event.text:
        parts = event.text.split(None, 1)
        if len(parts) > 1:
            raw_match = parts[1]
    match = raw_match.strip()

    if not event.reply_to_message:
        return await event.reply("Please reply to a message.")

    msg = await event.reply("Creating quote, please wait.")
    reply = event.reply_to_message
    replied_to, reply_ = None, None

    if match:
        spli_ = match.split(maxsplit=1)
        if (spli_[0] in ["r", "reply"]) or (
            spli_[0].isdigit() and int(spli_[0]) in range(1, 21)
        ):
            if spli_[0].isdigit():
                count = int(spli_[0])
                msg_ids = [mid for mid in range(reply.id - count + 1, reply.id + 1) if mid > 0]
                msgs = await app.get_messages(
                    event.chat.id,
                    message_ids=msg_ids,
                )
                if not isinstance(msgs, list):
                    msgs = [msgs]
                reply_ = [m for m in msgs if m and not getattr(m, "empty", False)]
                if not reply_:
                    reply_ = [reply]
                else:
                    reply_.sort(key=lambda m: m.id)
            else:
                replied_to = reply.reply_to_message
            try:
                match = spli_[1]
            except IndexError:
                match = None

    user = None

    if not reply_:
        reply_ = reply

    if match:
        match = match.split(maxsplit=1)

    if match:
        if match[0].startswith("@") or match[0].isdigit():
            try:
                user = await app.get_users(match[0].lstrip("@"))
            except Exception:
                pass
            match = match[1] if len(match) == 2 else None
        else:
            match = match[0]

    if match == "random":
        match = choice(Quotly._COLORS)

    file = None
    try:
        file = await quotly.create_quotly(
            reply_, bg=match, reply=replied_to, sender=user
        )
        message = await event.reply_photo(file)
    except (
        httpx.HTTPError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        Exception,
    ) as error:
        await msg.edit(f"Quote generation failed: {error}")
        return
    finally:
        if file and os.path.exists(file):
            try:
                os.remove(file)
            except OSError:
                pass
    await msg.delete()
    return message


# <=================================================== HELP ====================================================>


__mod_name__ = "QUOTELY"

__help__ = """   
»  /q : Create quote.

» /q r : Get replied quote.

» /q 2 ᴛᴏ 8 : Get multiple quotes.

» /q < any colour name > : Create any coloured quotes.

➠ Example:

» /q red , /q blue etc.
"""
# <================================================ END =======================================================>
