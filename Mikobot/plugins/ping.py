# <============================================== IMPORTS =========================================================>
import time

from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from Mikobot import StartTime, dp
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.human_read import get_readable_time

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
@check_admin(only_dev=True)
async def ptb_ping(message: Message):
    start_time = time.time()
    sent = await message.answer("Pining")
    end_time = time.time()
    telegram_ping = str(round((end_time - start_time) * 1000, 3)) + " ms"
    uptime = get_readable_time((time.time() - StartTime))

    await sent.edit_text(
        "🏓 <b>PONG</b>\n\n"
        "<b>Time taken:</b> <code>{}</code>\n"
        "<b>Uptime:</b> <code>{}</code>".format(telegram_ping, uptime),
        parse_mode=ParseMode.HTML,
    )


# <=======================================================================================================>


# <================================================ HANDLER =======================================================>
dp.message.register(ptb_ping, Command("ping"))
# <================================================ END =======================================================>
