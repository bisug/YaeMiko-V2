# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from Mikobot import LOGGER, dp
from Mikobot.state import state

# <=======================================================================================================>

DOWNLOADING_STICKER_ID = (
    "CAACAgIAAxkBAAEDv_xlJWmh2-fKRwvLywJaFeGy9wmBKgACVQADr8ZRGmTn_PAl6RC_MAQ"
)
API_URL = "https://karma-api2.vercel.app/instadl"  # Replace with your actual API URL


# <================================================ FUNCTION =======================================================>
async def instadl_command_handler(message: Message, command: CommandObject):
    if len(command.args) < 1:
        await message.answer("Usage: /instadl [Instagram URL]")
        return

    link = command.args[0]
    downloading_sticker = None
    try:
        downloading_sticker = await message.answer_sticker(DOWNLOADING_STICKER_ID)

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
                await message.answer_photo(content_url)
            elif content_type == "video":
                await message.answer_video(content_url)
            else:
                await message.answer("Unsupported content type.")
        else:
            await message.answer(
                "Unable to fetch content. Please check the Instagram URL or try with another Instagram link."
            )

    except Exception:
        LOGGER.exception("Instagram download request failed")
        await message.answer(
            "An error occurred while processing the request."
        )

    finally:
        if downloading_sticker is not None:
            try:
                await downloading_sticker.delete()
            except Exception:
                pass


dp.message.register(
    instadl_command_handler,
    Command(["ig", "instagram", "insta", "instadl"]),
)
# <================================================ END =======================================================>
