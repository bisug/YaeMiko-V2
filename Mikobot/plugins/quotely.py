# <============================================== IMPORTS =========================================================>
import base64
import os
import tempfile
from random import choice

import aiohttp
from aiohttp import ContentTypeError
from PIL import Image
from pyrogram.enums import MessageEntityType


def get_display_name(user):
    if user is None:
        return None
    return " ".join(part for part in (user.first_name, user.last_name) if part) or None

from Mikobot import DEV_USERS, app
from Mikobot.events import register

# <=======================================================================================================>


# <================================================ CLASS & FUNCTION =======================================================>
class Quotly:
    _API = "https://bot.lyo.su/quote/generate"
    _COLORS = (
        "#1b1429", "#2b1b3d", "#123456", "#0f2027", "#42275a",
        "#2c3e50", "#3a1c71", "#4b1248", "#1f4037", "#16222a",
    )
    _entities = {
        MessageEntityType.PHONE_NUMBER: "phone_number",
        MessageEntityType.MENTION: "mention",
        MessageEntityType.BOLD: "bold",
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
    }

    async def _format_quote(self, event, reply=None, sender=None, type_="private"):
        async def telegraph(file_):
            with Image.open(file_) as image:
                converted = image.convert("RGB")
                converted.save(file_, "PNG")
            with open(file_, "rb") as source:
                files = {"file": source.read()}
            try:
                return "https://telegra.ph" + (
                    await async_searcher(
                        "https://telegra.ph/upload", post=True, data=files, re_json=True
                    )
                )[0]["src"]
            finally:
                if os.path.exists(file_):
                    os.remove(file_)

        reply = (
            {
                "name": get_display_name(reply.from_user) or "Deleted Account",
                "text": reply.text,
                "chatId": reply.chat.id,
            }
            if reply
            else {}
        )

        is_fwd = event.fwd_from
        name, last_name = None, None

        if sender and sender.id not in DEV_USERS:
            id_ = sender.id
            name = get_display_name(sender)
        elif not is_fwd:
            id_ = event.from_user.id if event.from_user else None
            sender = event.from_user
            name = get_display_name(sender)
        else:
            id_, sender = None, None
            name = is_fwd.from_name
            if is_fwd.from_id:
                id_ = is_fwd.from_id
                try:
                    sender = await app.get_users(id_)
                    name = get_display_name(sender)
                except ValueError:
                    pass
        if sender and hasattr(sender, "last_name"):
            last_name = sender.last_name

        entities = (
            [
                {
                    "type": self._entities[entity.type],
                    "offset": entity.offset,
                    "length": entity.length,
                    **({"url": entity.url} if entity.url else {}),
                    **(
                        {
                            "user": {
                                "id": entity.user.id,
                                "first_name": entity.user.first_name,
                                "last_name": entity.user.last_name,
                                "username": entity.user.username,
                            }
                        }
                        if entity.user
                        else {}
                    ),
                    **({"language": entity.language} if entity.language else {}),
                    **(
                        {"custom_emoji_id": entity.custom_emoji_id}
                        if entity.custom_emoji_id
                        else {}
                    ),
                }
                for entity in event.entities
            ]
            if event.entities
            else []
        )

        message = {
            "entities": entities,
            "chatId": id_,
            "avatar": True,
            "from": {
                "id": id_,
                "first_name": (name or (sender.first_name if sender else None))
                or "Deleted Account",
                "last_name": last_name,
                "username": sender.username if sender else None,
                "language_code": "en",
                "title": name,
                "name": name or "Unknown",
                "type": type_,
            },
            "text": event.text,
            "replyMessage": reply,
        }

        if event.document and event.document.thumbs:
            file_ = await event.download_media(thumb=-1)
            uri = await telegraph(file_)
            message["media"] = {"url": uri}

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
        except ContentTypeError as er:
            if url != self._API:
                return await self.create_quotly(self._API)
            raise er

        if request.get("ok"):
            with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as file:
                file_name = file.name
                file.write(base64.b64decode(request["result"]["image"]))
            return file_name
        raise Exception(str(request))


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
    **kwargs
):
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as client:
        request = client.post(url, json=json, data=data, ssl=ssl, *args, **kwargs) if post else client.get(url, params=params, ssl=ssl, *args, **kwargs)
        response = await request
        response.raise_for_status()
        if re_json:
            return await response.json()
        if re_content:
            return await response.read()
        return await response.text()


@register(pattern="^/q(?: |$)(.*)")
async def quott_(event):
    match = (
        (event.command[1] if event.command and len(event.command) > 1 else "")
        .strip()
    )
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
                reply_ = await app.get_messages(
                    event.chat.id,
                    message_ids=range(reply.id - int(spli_[0]) + 1, reply.id + 1),
                )
                if not isinstance(reply_, list):
                    reply_ = [reply_]
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
            except ValueError:
                pass
            match = match[1] if len(match) == 2 else None
        else:
            match = match[0]

    if match == "random":
        match = choice(Quotly._COLORS)

    try:
        file = await quotly.create_quotly(reply_, bg=match, reply=replied_to, sender=user)
        message = await event.reply_photo(file)
    except (aiohttp.ClientError, OSError, KeyError, TypeError, ValueError) as error:
        await msg.edit(f"Quote generation failed: {error}")
        return
    finally:
        if 'file' in locals() and os.path.exists(file):
            os.remove(file)
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
