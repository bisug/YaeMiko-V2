from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import ChatAdminRequired, UserAdminInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from Mikobot import SUPPORT_STAFF, app


async def is_administrator(user_id, message):
    if user_id in SUPPORT_STAFF:
        return True
    member = await app.get_chat_member(message.chat.id, user_id)
    return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


async def has_ban_rights(message, user_id=None):
    target = user_id or (await app.get_me()).id
    member = await app.get_chat_member(message.chat.id, target)
    return bool(getattr(member.privileges, "can_restrict_members", False))


async def _count_deleted(message):
    return sum(1 async for member in app.get_chat_members(message.chat.id) if member.user.is_deleted)


async def _remove_deleted(message, status):
    removed = skipped = 0
    async for member in app.get_chat_members(message.chat.id):
        if not member.user.is_deleted:
            continue
        try:
            await app.ban_chat_member(message.chat.id, member.user.id)
            await app.unban_chat_member(message.chat.id, member.user.id)
            removed += 1
        except UserAdminInvalid:
            skipped += 1
        except ChatAdminRequired:
            await status.edit("I need permission to ban members in this group.")
            return
    result = f"Removed {removed} deleted account(s)."
    if skipped:
        result += f" Skipped {skipped} admin account(s)."
    await status.edit(result, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="zombies_close")]]))


@app.on_message(filters.regex(r"^[!/]zombies(?:\s+(clean))?(?:@\S+)?$"), group=1)
async def zombies(_, message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return await message.reply("Zombies can only be checked in groups or supergroups.")
    clean = len(message.command or []) > 1 and message.command[1].lower() == "clean"
    if not clean:
        deleted = await _count_deleted(message)
        if not deleted:
            return await message.reply("Group is clean; no deleted accounts found.")
        allowed = await is_administrator(message.from_user.id, message) and await has_ban_rights(message) and await has_ban_rights(message, message.from_user.id)
        button = "Remove" if allowed else "Close"
        return await message.reply(
            f"Found {deleted} deleted account(s).\n" + ("You can remove them." if allowed else "Only an admin with ban permission can remove them."),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(button, callback_data="zombies_remove" if allowed else "zombies_close")]]),
        )
    if not await is_administrator(message.from_user.id, message):
        return await message.reply("You need to be an admin to remove deleted accounts.")
    status = await message.reply("Removing deleted accounts…")
    await _remove_deleted(message, status)


@app.on_callback_query(filters.regex(r"^zombies_(remove|close)$"))
async def zombies_callback(_, callback):
    if callback.data == "zombies_close":
        await callback.answer("Closed.")
        await callback.message.delete()
        return
    if not await is_administrator(callback.from_user.id, callback.message):
        return await callback.answer("You need admin permission.", alert=True)
    await callback.answer("Removing deleted accounts…", alert=True)
    status = await callback.message.edit("Removing deleted accounts…")
    await _remove_deleted(callback.message, status)


__help__ = """
➠ <b>Remove Deleted Accounts:</b>

» /zombies — find deleted accounts in a group
» /zombies clean — remove deleted accounts from a group
"""
__mod_name__ = "ZOMBIES"
