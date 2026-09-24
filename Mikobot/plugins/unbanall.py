import os
from asyncio import sleep
from pyrogram.enums import ChatType


from pyrogram.enums import ChatMemberStatus, ChatMembersFilter
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.types import ChatPermissions

from Mikobot import LOGGER, app
from Mikobot.events import register


async def is_admin(chat_id, user_id):
    try:
        member = await app.get_chat_member(chat_id, user_id)
    except UserNotParticipant:
        return False
    return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


@register(pattern=r"^/(?:unbanall|unmuteall)(?:@\S+)?$")
async def bulk_moderation(message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return await message.reply("This command can be used in groups and supergroups only.")
    command = message.command[0].lower() if message.command else ""
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("Only admins can use this command.")
    bot_member = await app.get_chat_member(message.chat.id, (await app.get_me()).id)
    if not getattr(bot_member.privileges, "can_restrict_members", False):
        return await message.reply("I need permission to restrict members.")
    member_filter = ChatMembersFilter.BANNED if command == "/unbanall" else ChatMembersFilter.RESTRICTED
    status = await message.reply("Searching participant list...")
    count = 0
    async for member in app.get_chat_members(message.chat.id, filter=member_filter):
        try:
            if command == "/unbanall":
                await app.unban_chat_member(message.chat.id, member.user.id)
            else:
                await app.restrict_chat_member(
                    message.chat.id,
                    member.user.id,
                    ChatPermissions(can_send_messages=True),
                )
            count += 1
        except FloodWait as error:
            await sleep(error.value)
        except Exception:
            LOGGER.exception("Bulk moderation failed for chat %s", message.chat.id)
    await status.edit(f"Successfully updated {count} users.")


@register(pattern=r"^/users(?:@\S+)?$")
async def get_users(message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if not await is_admin(message.chat.id, message.from_user.id):
        return
    chat = await app.get_chat(message.chat.id)
    lines = [f"Users in {chat.title or 'this chat'}:"]
    async for member in app.get_chat_members(message.chat.id):
        user = member.user
        if user.is_deleted:
            lines.append(f"Deleted Account {user.id}")
        else:
            name = user.first_name or "Unknown"
            lines.append(f"[{name}](tg://user?id={user.id}) {user.id}")
    path = f"userslist_{message.chat.id}.txt"
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))
        await message.reply_document(path, caption=f"Users in {chat.title or 'this chat'}")
    finally:
        if os.path.exists(path):
            os.remove(path)


__mod_name__ = "Unbanll"
