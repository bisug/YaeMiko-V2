# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>
from aiogram.filters import Command, CommandObject
from pyrogram.types import Message

from Mikobot import LOGGER, dp
from Mikobot.state import state

# <=======================================================================================================>

DOWNLOADING_STICKER_ID = (
    "CAACAgIAAxkBAAEDv_xlJWmh2-fKRwvLywJaFeGy9wmBKgACVQADr8ZRGmTn_PAl6RC_MAQ"
)
API_URL = "https://karma-api2.vercel.app/instadl"  # Replace with your actual API URL


# <================================================ FUNCTION =======================================================>
async def instadl_command_handler(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) < 1:
        await message.reply_text("Usage: /instadl [Instagram URL]")
        return

    link = args[0]
    downloading_sticker = None
    try:
        downloading_sticker = await message.reply_sticker(DOWNLOADING_STICKER_ID)

        # Make an asynchronous GET request to the API using httpx
        response = await state.get(API_URL, params={"url": link})
        data = response.json()

        # Check if the API request was successful
        if "content_url" in data:
            content_url = data["content_url"]

            # Determine content type from the URL
            content_type = "video" if "video" in content_url else "photo"

            # Reply with either photo or video
            if content_type == "photo":
                await message.reply_photo(content_url)
            elif content_type == "video":
                await message.reply_video(content_url)
            else:
                await message.reply_text("Unsupported content type.")
        else:
            await message.reply_text(
                "Unable to fetch content. Please check the Instagram URL or try with another Instagram link."
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


dp.message.register(
    instadl_command_handler,
    Command(commands=["ig", "instagram", "insta", "instadl"]),
)
# <================================================ END =======================================================>
