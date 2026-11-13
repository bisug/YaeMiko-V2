from urllib.parse import urlparse

import httpx
from pyrogram import filters
from pyrogram.types import Message

from Mikobot.events import on_message
from Mikobot.state import state

# <================================================ FUNCTIONS =====================================================>
COSPLAY_API_URL = "https://sugoi-api.vercel.app/cosplay"
REQUEST_TIMEOUT = 15


def _valid_image_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def get_cosplay_data() -> str:
    response = await state.get(COSPLAY_API_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    photo_url = data.get("url") if isinstance(data, dict) else None
    if not _valid_image_url(photo_url):
        raise ValueError("The cosplay service returned an invalid image URL.")
    return photo_url


@on_message(filters.command("cosplay"), chained=True)
async def cosplay(client, message: Message):
    status = await message.reply_text("Fetching a cosplay photo...")
    try:
        photo_url = await get_cosplay_data()
        await message.reply_photo(photo=photo_url)
    except httpx.HTTPError, ValueError, KeyError, TypeError:
        await status.edit_text(
            "Unable to fetch a cosplay photo right now. Please try again later."
        )
        return
    finally:
        try:
            await status.delete()
        except Exception:
            pass


__mod_name__ = "COSPLAY"
__command_list__ = ["cosplay"]
# <================================================ END =======================================================>
