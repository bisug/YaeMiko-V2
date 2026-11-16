# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

from pyrogram import filters
from pyrogram.types import Message

from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.state import state

DOWNLOADING_STICKER_ID = (
    "CAACAgIAAxkBAAEDv_xlJWmh2-fKRwvLywJaFeGy9wmBKgACVQADr8ZRGmTn_PAl6RC_MAQ"
)
API_URL = "https://karma-api2.vercel.app/instadl"


@on_message(filters.command(["ig", "instagram", "insta", "instadl"]), chained=True)
async def instadl_command_handler(client, message: Message):
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) < 1:
        await message.reply_text("Usage: /instadl [Instagram URL]")
        return

    link = args[0]
    downloading_sticker = None
    try:
        downloading_sticker = await message.reply_sticker(DOWNLOADING_STICKER_ID)

        response = await state.get(API_URL, params={"url": link}, timeout=15)
        data = response.json()

        if "content_url" in data:
            content_url = data["content_url"]

            content_type = "video" if "video" in content_url else "photo"

            if content_type == "photo":
                await message.reply_photo(content_url)
            elif content_type == "video":
                await message.reply_video(content_url)
            else:
                await message.reply_text("Unsupported content type.")
        else:
            await message.reply_text(
                "Unable to fetch content. Check the URL or try another Instagram link."
            )

    except Exception:
        LOGGER.exception("Instagram download request failed")
        await message.reply_text("An error occurred while processing the request.")

    finally:
        if downloading_sticker is not None:
            try:
                await downloading_sticker.delete()
            except Exception:
                pass


__mod_name__ = "Instadl"
__command_list__ = ["ig", "instagram", "insta", "instadl"]
