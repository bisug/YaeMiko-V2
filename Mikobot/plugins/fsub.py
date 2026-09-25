from time import perf_counter

from cachetools import TTLCache
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import ChatAdminRequired, UserNotParticipant
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup

from Database.mongodb import fsub_db as db
from Mikobot import BOT_ID, DRAGONS as DEVS, LOGGER, OWNER_ID, app
from Mikobot.events import register
from pyrogram.enums import ButtonStyle

F_SUBSCRIBE_COMMAND = r"/(fsub|Fsub|forcesubscribe|Forcesub|forcesub|Forcesubscribe)"
FORCESUBSCRIBE_ON = {"on", "yes", "y"}
FORCESUBSCRIBE_OFF = {"off", "no", "n"}
BOT_PRIVILEGE_CACHE = TTLCache(maxsize=10_000, ttl=600, timer=perf_counter)



async def is_admin(chat_id, user_id):
    try:
        member = await app.get_chat_member(chat_id, user_id)
    except UserNotParticipant:
        return False
    return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


async def participant_check(channel, user_id):
    try:
        await app.get_chat_member(channel, int(user_id))
        return True
    except (UserNotParticipant, ChatAdminRequired):
        return False
    except Exception:
        LOGGER.exception(
            "Unable to check channel %s membership for user %s", channel, user_id
        )
        return True


@register(pattern=rf"^{F_SUBSCRIBE_COMMAND} ?(.*)")
async def force_subscribe(message):
    if message.chat.type == ChatType.PRIVATE:
        return
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        member = await app.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            return await message.reply("You need to be an admin to do this.")
        if member.status != ChatMemberStatus.OWNER:
            return await message.reply("❗ Group creator required\nYou have to be the group creator to do that.")
    parts = message.text.split(None, 1)
    channel = parts[1] if len(parts) > 1 else None
    if not channel:
        chat_db = await db.fs_settings(message.chat.id)
        if not chat_db:
            await message.reply("Force subscribe is disabled in this chat.")
        else:
            await message.reply(f"Force subscribe is currently enabled. Users are forced to join @{chat_db.channel} to speak here.")
        return
    if channel.lower() in FORCESUBSCRIBE_ON:
        return await message.reply("Please specify the channel username.")
    if channel.lower() in FORCESUBSCRIBE_OFF:
        await db.disapprove(message.chat.id)
        return await message.reply("**Force subscribe is disabled successfully.**")
    try:
        channel_entity = await app.get_chat(channel)
    except Exception:
        return await message.reply("Invalid channel username provided.")
    username = getattr(channel_entity, "username", None)
    if not username or channel_entity.type != ChatType.CHANNEL:
        return await message.reply("That's not a valid channel.")
    if not await participant_check(username, BOT_ID):
        return await message.reply(f"**Not an admin in the channel**\nI am not an admin in the [channel](https://t.me/{username}). Add me as an admin to enable force subscribe.")
    await db.add_channel(message.chat.id, str(username))
    await message.reply(f"Force subscribe is enabled to @{username}.")


@app.on_message(filters.group & filters.incoming)
async def force_subscribe_new_message(_, message):
    settings = await db.fs_settings(message.chat.id)
    if not settings:
        return
    if not message.from_user or message.from_user.id in DEVS or message.from_user.id == OWNER_ID:
        return
    try:
        sender = await app.get_chat_member(message.chat.id, message.from_user.id)
        if sender.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            return
    except UserNotParticipant:
        return
    except Exception:
        LOGGER.exception("Unable to check force-subscribe sender privileges")
        return
    try:
        if message.chat.id not in BOT_PRIVILEGE_CACHE:
            bot = await app.get_chat_member(message.chat.id, BOT_ID)
            BOT_PRIVILEGE_CACHE[message.chat.id] = bool(
                getattr(bot.privileges, "can_restrict_members", False)
            )
        if not BOT_PRIVILEGE_CACHE[message.chat.id]:
            return
    except Exception:
        LOGGER.exception(
            "Unable to check bot privileges for force-subscribe chat %s",
            message.chat.id,
        )
        return
    channel = settings["channel"]
    if await participant_check(channel, message.from_user.id):
        return
    name = message.from_user.first_name.replace("<", "&lt;").replace(">", "&gt;")
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel}", style=ButtonStyle.SUCCESS),
        InlineKeyboardButton("Unmute Me", callback_data=f"fs_{message.from_user.id}", style=ButtonStyle.SUCCESS),
    ]])
    await message.reply(
        f'<b><a href="tg://user?id={message.from_user.id}">{name}</a></b>, you have <b>not subscribed</b> to our <b><a href="https://t.me/{channel}">channel</a></b> yet. Please join and press the button below to unmute yourself.',
        reply_markup=markup,
    )
    await app.restrict_chat_member(message.chat.id, message.from_user.id, ChatPermissions(can_send_messages=False))


@app.on_callback_query(filters.regex(r"^fs_(\d+)$"))
async def unmute_force_subscribe(client, callback):
    user_id = int(callback.matches[0].group(1))
    if callback.from_user.id != user_id:
        return await callback.answer("This is not meant for you.", alert=True)
    settings = await db.fs_settings(callback.message.chat.id)
    if not settings:
        return await callback.answer("Force subscribe is disabled.", alert=True)
    channel = settings["channel"]
    if not await participant_check(channel, user_id):
        return await callback.answer("You have to join the channel first, to get unmuted!", alert=True)
    await app.restrict_chat_member(callback.message.chat.id, user_id, ChatPermissions(can_send_messages=True))
    await callback.answer("You are unmuted.")
    await callback.message.delete()


__mod_name__ = "F-SUB"
__help__ = r"""
➠ *Dazai has the capability to hush members who haven't yet subscribed to your channel until they decide to hit that subscribe button.*
➠ *When activated, I'll silence those who are not subscribed and provide them with an option to unmute. Once they click the button, I'll lift the mute.*

➠ Configuration Process
➠ Exclusively for Creators
➠ Grant me admin privileges in your group
➠ Designate me as an admin in your channel

➠ *Commands*
» /fsub channel\_username - to initiate and customize settings for the channel.

➠ *Kick things off with...*
» /fsub - to review the current settings.
» /fsub off - to deactivate the force subscription feature.

➠ *If you disable fsub, you'll need to set it up again for it to take effect. Utilize /fsub channel\_username.*
"""
# <================================================ END =======================================================>
