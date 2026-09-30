# <============================================== IMPORTS =========================================================>
import html
import random
from datetime import datetime

import humanize
from aiogram import F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from Database.sql import afk_sql as sql
from Mikobot import dp
from Mikobot.plugins.disable import disableable, disableable_friendly
from Mikobot.plugins.helper_funcs.string_handling import entities_map
from Mikobot.plugins.users import get_user_id
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.gate import chain

# <=======================================================================================================>

MENTION_ENTITIES = ["text_mention", "mention"]


# <================================================ FUNCTION =======================================================>
async def afk(message: Message):
    if not message.text:
        return
    args = message.text.split(None, 1)
    user = message.from_user

    if not user:  # ignore channels
        return

    notice = ""
    if len(args) >= 2:
        reason = args[1]
        if len(reason) > 100:
            reason = reason[:100]
            notice = "\nYour afk reason was shortened to 100 characters."
    else:
        reason = ""

    sql.set_afk(user.id, reason)
    fname = user.first_name
    try:
        if reason:
            await message.answer(
                f"➲ {fname} is now away! \n\n➦ Reason: <code>{reason}</code> \n {notice}",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer("➲ {} is now away!{}".format(fname, notice))
    except TelegramAPIError:
        pass


async def no_longer_afk(message: Message):
    user = message.from_user

    if not user:  # ignore channels
        return

    if not sql.is_afk(user.id):
        return

    afk_user = sql.check_afk_status(user.id)
    time = humanize.naturaldelta(datetime.now() - afk_user.time)
    res = sql.rm_afk(user.id)
    if res:
        if message.new_chat_members:  # dont say msg
            return
        firstname = user.first_name
        try:
            options = [
                "➲ {} is here!",
                "➲ {} is back!",
                "➲ {} is now in the chat!",
                "➲ {} is awake!",
                "➲ {} is back online!",
                "➲ {} is finally here!",
                "➲ Welcome back! {}",
            ]
            chosen_option = random.choice(options)
            await message.answer(
                chosen_option.format(firstname)
                + f"\n\nYou were AFK for: <code>{time}</code>",
                parse_mode=ParseMode.HTML,
            )
        except TelegramAPIError:
            return


async def reply_afk(message: Message):
    userc = message.from_user
    userc_id = userc.id
    chk_users = []

    if message.entities and entities_map(message, MENTION_ENTITIES):
        entities = list(entities_map(message, MENTION_ENTITIES))
        ent = entities[0] if entities else None
        if ent.type == "text_mention":
            user_id = ent.user.id
            fst_name = ent.user.first_name

            if user_id in chk_users:
                return
            chk_users.append(user_id)
        elif ent.type != "mention":
            return
        else:
            user_id = await get_user_id(
                message.text[ent.offset : ent.offset + ent.length],
            )
            if not user_id:
                return

            if user_id in chk_users:
                return
            chk_users.append(user_id)

            fst_name = message.text[ent.offset : ent.offset + ent.length].lstrip("@")
            await check_afk(message, user_id, fst_name, userc_id)

    elif message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        fst_name = message.reply_to_message.from_user.first_name
        await check_afk(message, user_id, fst_name, userc_id)


async def check_afk(
    message: Message,
    user_id: int,
    fst_name: str,
    userc_id: int,
):
    if sql.is_afk(user_id):
        user = sql.check_afk_status(user_id)

        if int(userc_id) == int(user_id):
            return

        time = humanize.naturaldelta(datetime.now() - user.time)

        if not user.reason:
            res = "➲ {} is afk.\n\n➦ Last seen {} ago.".format(
                fst_name,
                time,
            )
            await message.answer(res)
        else:
            res = (
                "➲ {} is afk.\n\n➦ Reason: <code>{}</code>\n➦ Last seen {} ago.".format(
                    html.escape(fst_name),
                    html.escape(user.reason),
                    time,
                )
            )
            await message.answer(res, parse_mode=ParseMode.HTML)


# <=================================================== HELP ====================================================>


__help__ = """
» /afk <reason>*:* mark yourself as AFK (away from keyboard).

» brb , !afk <reason>*:* same as the afk command - but not a command.

» /bye [Reason > Optional] - Tell others that you are AFK (Away From Keyboard).

» /bye [reply to media] - AFK with media.

» /byedel - Enable auto delete AFK message in group (Only for group admin). Default is **Enable**.

➠ *When marked as AFK, any mentions will be replied to with a message to say you're not available!*
"""

# <================================================ HANDLER =======================================================>
# Every one of these matched a message in PTB and all of them ran, so each is
# chained; otherwise the first match would swallow the rest.
dp.message.register(chain(afk), *disableable("afk"))
dp.message.register(
    chain(afk),
    disableable_friendly("afk"),
    F.text.regexp(r"^(?i:(brb|!afk))( .*)?$"),
)
dp.message.register(chain(no_longer_afk), GROUPS)
dp.message.register(chain(reply_afk), GROUPS)

__mod_name__ = "AFK"
__command_list__ = ["afk"]
# <================================================ END =======================================================>
