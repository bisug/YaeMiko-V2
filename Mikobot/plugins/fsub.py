from time import perf_counter

from cachetools import TTLCache
from pyrogram import StopPropagation, filters
from pyrogram.enums import ButtonStyle, ChatMemberStatus, ChatType
from pyrogram.errors import ChatAdminRequired, UserNotParticipant
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup

from Database.sql import fsub_sql as db
from Mikobot import BOT_ID, OWNER_ID, app
from Mikobot import DRAGONS as DEVS
from Mikobot.events import on_callback, on_message, register
from Mikobot.logger import LOGGER
from Mikobot.utils.can_restrict import has_restrict_rights

F_SUBSCRIBE_COMMAND = r"/(fsub|Fsub|forcesubscribe|Forcesub|forcesub|Forcesubscribe)"
FORCESUBSCRIBE_ON = {"on", "yes", "y"}
FORCESUBSCRIBE_OFF = {"off", "no", "n"}
BOT_PRIVILEGE_CACHE = TTLCache(maxsize=10_000, ttl=600, timer=perf_counter)


async def participant_check(channel, user_id):
    try:
        await app.get_chat_member(channel, int(user_id))
        return True
    except UserNotParticipant, ChatAdminRequired:
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
    if not message.from_user:
        return await message.reply_text("Only users can configure force subscribe.")
    if message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        member = await app.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        }:
            return await message.reply_text("You need to be an admin to do this.")
        if member.status != ChatMemberStatus.OWNER:
            return await message.reply_text(
                "Group creator required.\nOnly the group creator can do that."
            )
    parts = message.text.split(None, 1)
    channel = parts[1] if len(parts) > 1 else None
    if not channel:
        chat_db = db.fs_settings(message.chat.id)
        if not chat_db:
            await message.reply_text("Force subscribe is disabled in this chat.")
        else:
            await message.reply_text(
                f"Force subscribe is enabled. Members must join @{chat_db['channel']} to speak here."
            )
        return
    if channel.lower() in FORCESUBSCRIBE_ON:
        return await message.reply_text("Please specify the channel username.")
    if channel.lower() in FORCESUBSCRIBE_OFF:
        db.disapprove(message.chat.id)
        return await message.reply_text("**Force subscribe is disabled.**")
    try:
        channel_entity = await app.get_chat(channel)
    except Exception:
        return await message.reply_text("Invalid channel username provided.")
    username = getattr(channel_entity, "username", None)
    if not username or channel_entity.type != ChatType.CHANNEL:
        return await message.reply_text("That's not a valid channel.")
    if not await participant_check(username, BOT_ID):
        return await message.reply_text(
            f"**Not an admin in the channel**\nThe bot is not an admin in the [channel](https://t.me/{username}). Add the bot as an admin to enable force subscribe."
        )
    db.add_channel(message.chat.id, str(username))
    await message.reply_text(f"Force subscribe is enabled for @{username}.")


@on_message(filters.group & filters.incoming, chained=True)
async def force_subscribe_new_message(client, message):
    settings = db.fs_settings(message.chat.id)
    if not settings:
        return
    if (
        not message.from_user
        or message.from_user.id in DEVS
        or message.from_user.id == OWNER_ID
    ):
        return
    try:
        sender = await client.get_chat_member(message.chat.id, message.from_user.id)
        if sender.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            return
    except UserNotParticipant:
        return
    except Exception:
        LOGGER.exception("Unable to check force-subscribe sender privileges")
        return
    try:
        if message.chat.id not in BOT_PRIVILEGE_CACHE:
            bot = await client.get_chat_member(message.chat.id, BOT_ID)
            BOT_PRIVILEGE_CACHE[message.chat.id] = has_restrict_rights(bot)
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
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Join Channel",
                    url=f"https://t.me/{channel}",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(
                    text="Unmute Me",
                    callback_data=f"fs_{message.from_user.id}",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        ]
    )
    await message.reply_text(
        f'<b><a href="tg://user?id={message.from_user.id}">{name}</a></b>, you have <b>not subscribed</b> to the <b><a href="https://t.me/{channel}">channel</a></b>. Join it and press the button below to unmute yourself.',
        reply_markup=markup,
    )
    await client.restrict_chat_member(
        message.chat.id, message.from_user.id, ChatPermissions(can_send_messages=False)
    )
    raise StopPropagation


@on_callback(filters.regex(r"^fs_(\d+)$"))
async def unmute_force_subscribe(client, callback):
    user_id = int(callback.matches[0].group(1))
    if callback.from_user.id != user_id:
        return await callback.answer("This is not meant for you.", show_alert=True)
    settings = db.fs_settings(callback.message.chat.id)
    if not settings:
        return await callback.answer("Force subscribe is disabled.", show_alert=True)
    channel = settings["channel"]
    if not await participant_check(channel, user_id):
        return await callback.answer(
            "Join the channel first to be unmuted.", show_alert=True
        )
    await app.restrict_chat_member(
        callback.message.chat.id, user_id, ChatPermissions(can_send_messages=True)
    )
    await callback.answer("You are unmuted.")
    await callback.message.delete()


__mod_name__ = "F-SUB"


def __migrate__(old_chat_id, new_chat_id):
    db.migrate_chat(old_chat_id, new_chat_id)


__help__ = r"""
Force subscribe mutes members who have not joined your channel until they subscribe. When active, the bot mutes unsubscribed members and offers an unmute button. Pressing the button lifts the mute.

Setup:
- Only the group creator can configure force subscribe.
- Add the bot as an admin in your group.
- Add the bot as an admin in your channel.

Commands:
/fsub <channel\_username>: Set the channel and enable force subscribe.
/fsub: Show the current settings.
/fsub off: Disable force subscribe.

After disabling force subscribe, set it again with /fsub <channel\_username> to take effect.
"""
