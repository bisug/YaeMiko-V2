# <============================================== IMPORTS =========================================================>
import asyncio

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import DEV_USERS
from Mikobot.events import on_callback, on_message
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def convert(speed):
    return round(int(speed) / 1048576, 2)


@on_message(*disableable("speedtest"), chained=True)
@check_admin(only_dev=True)
async def speedtestxyz(client, message: Message):
    buttons = [
        [
            InlineKeyboardButton(
                text="Image", callback_data="speedtest_image", style=ButtonStyle.PRIMARY
            ),
            InlineKeyboardButton(
                text="Text", callback_data="speedtest_text", style=ButtonStyle.PRIMARY
            ),
        ],
    ]
    await message.reply_text(
        "Select SpeedTest Mode",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@on_callback(filters.regex(r"^speedtest_"), chained=True)
async def speedtestxyz_callback(client, query: CallbackQuery):
    if query.data not in {"speedtest_image", "speedtest_text"}:
        await query.answer("Invalid selection.", show_alert=True)
        return

    if query.from_user.id in DEV_USERS:
        msg = await query.message.edit_text("Running a speedtest....")
        import speedtest

        speed = await asyncio.to_thread(speedtest.Speedtest)
        await asyncio.to_thread(speed.get_best_server)
        await asyncio.to_thread(speed.download)
        await asyncio.to_thread(speed.upload)
        replymsg = "SpeedTest Results:"

        if query.data == "speedtest_image":
            speedtest_image = await asyncio.to_thread(speed.results.share)
            await query.message.reply_photo(
                photo=speedtest_image,
                caption=replymsg,
            )
            await msg.delete()

        elif query.data == "speedtest_text":
            result = await asyncio.to_thread(speed.results.dict)
            replymsg += f"\nDownload: `{convert(result['download'])}Mb/s`\nUpload: `{convert(result['upload'])}Mb/s`\nPing: `{result['ping']}`"
            await query.message.edit_text(replymsg, parse_mode=ParseMode.MARKDOWN)
        await query.answer("Speedtest complete.")
    else:
        await query.answer("You are required to join Black Bulls to use this command.")


__mod_name__ = "SpeedTest"
__command_list__ = ["speedtest"]
# <================================================ END =======================================================>
