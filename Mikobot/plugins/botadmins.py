# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX


from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from Mikobot import DEMONS, DEV_USERS, DRAGONS, OWNER_ID, WOLVES
from Mikobot.events import on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.helper_funcs.chat_status import support_plus
from Mikobot.utils.parser import mention_html


async def get_user_info(user_id):
    return str(user_id)


async def get_users_info(user_ids):
    return [(await get_user_info(user_id), user_id) for user_id in user_ids]


async def get_users_list(user_ids):
    return [
        f"• {mention_html(user_id, name)} (<code>{user_id}</code>)"
        for name, user_id in await get_users_info(user_ids)
    ]


@support_plus
@on_message(filters.command("botadmins"), chained=True)
async def botstaff(client, message: Message):
    owner_info = mention_html(OWNER_ID, "Owner")
    reply = f"<b>Owner:</b> {owner_info} (<code>{OWNER_ID}</code>)\n"

    true_dev = list(set(DEV_USERS) - {OWNER_ID})
    reply += "\n\n<b>Special grade users:</b>\n"
    reply += "\n".join(await get_users_list(true_dev)) or "No Dev Users"

    true_sudo = list(set(DRAGONS) - set(DEV_USERS))
    reply += "\n\n<b>A grade users:</b>\n"
    reply += "\n".join(await get_users_list(true_sudo)) or "No Sudo Users"

    reply += "\n\n<b>B grade users:</b>\n"
    reply += "\n".join(await get_users_list(DEMONS)) or "No Demon Users"

    reply += "\n\n<b>Normal grade users:</b>\n"
    reply += (
        "\n".join(await get_users_list(WOLVES)) or "No additional whitelisted users"
    )

    await message.reply_text(reply, parse_mode=ParseMode.HTML)
    LOGGER.info(f"{message.from_user.id} fetched botstaff in {message.chat.id}")


__help__ = """
Bot admins only:
/stats: Show bot stats.
/ping: Check the bot's ping.
/gban: Ban a user globally.
/gbanlist: Show the global ban list.
/botadmins: Show the bot admin lists.
/gcast: Broadcast a message. Reply to the message to broadcast it.

Commands:
/broadcastall: Broadcast to all chats.
/broadcastusers: Broadcast to all users.
/broadcastgroups: Broadcast to all groups.
"""

__mod_name__ = "Bot Admin"
