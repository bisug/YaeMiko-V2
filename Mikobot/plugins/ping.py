# <============================================== IMPORTS =========================================================>
import time

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from Mikobot import StartTime
from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.human_read import get_readable_time

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
@on_message(filters.command("ping"), chained=True)
@check_admin(only_dev=True)
async def ptb_ping(client, message: Message):
    start_time = time.time()
    sent = await message.reply_text("Pining")
    end_time = time.time()
    telegram_ping = str(round((end_time - start_time) * 1000, 3)) + " ms"
    uptime = get_readable_time((time.time() - StartTime))

    await sent.edit_text(
        "🏓 <b>PONG</b>\n\n"
        "<b>Time taken:</b> <code>{}</code>\n"
        "<b>Uptime:</b> <code>{}</code>".format(telegram_ping, uptime),
        parse_mode=ParseMode.HTML,
    )


__mod_name__ = "PING"
__command_list__ = ["ping"]
# <================================================ END =======================================================>
