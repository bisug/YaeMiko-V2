import os
from asyncio import sleep

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter, ChatMemberStatus, ChatType
from pyrogram.errors import UserNotParticipant
from pyrogram.types import ChatPermissions, Message

from Mikobot import LOGGER
from Mikobot import app as client
from Mikobot.events import on_message
from Mikobot.utils.can_restrict import has_restrict_rights
from Mikobot.utils.errors import FLOOD_WAIT_ERRORS, flood_wait_seconds


async def is_admin(chat_id, user_id):
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except UserNotParticipant:
        return False
    return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


@on_message(filters.command(["unbanall", "unmuteall"]), chained=True)
async def bulk_moderation(client, message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return await message.reply_text(
            "This command can be used in groups and supergroups only."
        )
    command = message.command[0].lower() if message.command else ""
    if not message.from_user or not await is_admin(
        message.chat.id, message.from_user.id
    ):
        return await message.reply_text("Only admins can use this command.")
    bot_member = await client.get_chat_member(
        message.chat.id, (await client.get_me()).id
    )
    if not has_restrict_rights(bot_member):
        return await message.reply_text("I need permission to restrict members.")
    member_filter = (
        ChatMembersFilter.BANNED
        if command in {"/unbanall", "unbanall"}
        else ChatMembersFilter.RESTRICTED
    )
    status = await message.reply_text("Searching participant list...")
    count = 0
    async for member in client.get_chat_members(message.chat.id, filter=member_filter):
        try:
            if command in {"/unbanall", "unbanall"}:
                await client.unban_chat_member(message.chat.id, member.user.id)
            else:
                await client.restrict_chat_member(
                    message.chat.id,
                    member.user.id,
                    ChatPermissions(can_send_messages=True),
                )
            count += 1
        except FLOOD_WAIT_ERRORS as error:
            await sleep(flood_wait_seconds(error))
        except Exception:
            LOGGER.exception("Bulk moderation failed for chat %s", message.chat.id)
    await status.edit(f"Successfully updated {count} users.")


@on_message(filters.command("users"), chained=True)
async def get_users(client, message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if not message.from_user or not await is_admin(
        message.chat.id, message.from_user.id
    ):
        return
    chat = await client.get_chat(message.chat.id)
    lines = [f"Users in {chat.title or 'this chat'}:"]
    async for member in client.get_chat_members(message.chat.id):
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
        await message.reply_document(
            path, caption=f"Users in {chat.title or 'this chat'}"
        )
    finally:
        if os.path.exists(path):
            os.remove(path)


__mod_name__ = "Unbanll"
