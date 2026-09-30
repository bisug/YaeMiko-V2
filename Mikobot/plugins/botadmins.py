# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>

from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from Mikobot import DEMONS, DEV_USERS, DRAGONS, LOGGER, OWNER_ID, WOLVES, dp
from Mikobot.plugins.helper_funcs.chat_status import support_plus
from Mikobot.utils.parser import mention_html

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def get_user_info(user_id):
    return str(user_id)


async def get_users_info(user_ids):
    return [(await get_user_info(user_id), user_id) for user_id in user_ids]


async def get_users_list(user_ids):
    return [
        f"• {await mention_html(name, user_id)} (<code>{user_id}</code>)"
        for name, user_id in await get_users_info(user_ids)
    ]


@support_plus
async def botstaff(message: Message):
    owner_info = await mention_html("Owner", OWNER_ID)
    reply = f"✪ <b>OWNER :</b> {owner_info} (<code>{OWNER_ID}</code>)\n"

    true_dev = list(set(DEV_USERS) - {OWNER_ID})
    reply += "\n\n➪ <b>SPECIAL GRADE USERS :</b>\n"
    reply += "\n".join(await get_users_list(true_dev)) or "No Dev Users"

    true_sudo = list(set(DRAGONS) - set(DEV_USERS))
    reply += "\n\n➪ <b>A GRADE USERS :</b>\n"
    reply += "\n".join(await get_users_list(true_sudo)) or "No Sudo Users"

    reply += "\n\n➪ <b>B GRADE USERS :</b>\n"
    reply += "\n".join(await get_users_list(DEMONS)) or "No Demon Users"

    reply += "\n\n➪ <b>NORMAL GRADE USERS :</b>\n"
    reply += (
        "\n".join(await get_users_list(WOLVES))
        or "No additional whitelisted users"
    )

    await message.answer(reply, parse_mode=ParseMode.HTML)
    LOGGER.info(
        f"{message.from_user.id} fetched botstaff in {message.chat.id}"
    )


# <================================================ HANDLER =======================================================>
dp.message.register(botstaff, Command("botadmins"))
# <================================================ END =======================================================>


# <=================================================== HELP ====================================================>
__help__ = """
➠ *BOT ADMINS ONLY:*

» /stats: Shows bot stats.

» /ping: see ping.

» /gban: Global ban.

» /gbanlist: Shows gban list.

» /botadmins: Opens Bot admin lists.

» /gcast: Advance broadcast system. Just reply to any message.

➠ *Write with text message*

» /broadcastall

» /broadcastusers

» /broadcastgroups
"""

__mod_name__ = "BOT-ADMIN"
# <================================================ HANDLER =======================================================>
