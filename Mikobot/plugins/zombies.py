# <============================================== IMPORTS =========================================================>
from telethon import Button, events
from telethon.errors import ChatAdminRequiredError, UserAdminInvalidError
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights

from Mikobot import SUPPORT_STAFF, tbot

# <=======================================================================================================>

BANNED_RIGHTS = ChatBannedRights(
    until_date=None,
    view_messages=True,
    send_messages=True,
    send_media=True,
    send_stickers=True,
    send_gifs=True,
    send_games=True,
    send_inline=True,
    embed_links=True,
)

UNBAN_RIGHTS = ChatBannedRights(
    until_date=None,
    send_messages=None,
    send_media=None,
    send_stickers=None,
    send_gifs=None,
    send_games=None,
    send_inline=None,
    embed_links=None,
)


# <==================================================== FUNCTION ===================================================>
def _is_group(message) -> bool:
    return bool(
        getattr(message, "is_group", False)
        or getattr(message, "is_supergroup", False)
    )


async def is_administrator(user_id: int, message) -> bool:
    if user_id in SUPPORT_STAFF:
        return True
    permissions = await message.client.get_permissions(message.chat_id, user_id)
    return bool(permissions.is_admin or getattr(permissions, "is_creator", False))


async def has_ban_rights(message, user_id: int | None = None) -> bool:
    target = user_id or (await message.client.get_me()).id
    permissions = await message.client.get_permissions(message.chat_id, target)
    return bool(permissions.ban_rights)


async def _count_deleted(message) -> int:
    return sum(
        1
        async for participant in message.client.iter_participants(message.chat_id)
        if participant.deleted
    )


@tbot.on(events.NewMessage(pattern=r"^[!/]zombies(?:\s+(clean))?$", outgoing=False))
async def rm_deletedacc(message):
    if not _is_group(message):
        return await message.reply("Zombies can only be checked in groups or supergroups.")

    command = message.pattern_match.group(1)
    if not command:
        status = await message.reply("`Searching for deleted accounts…`")
        deleted = await _count_deleted(message)
        if deleted:
            can_remove = (
                await is_administrator(message.sender_id, message)
                and await has_ban_rights(message, message.sender_id)
                and await has_ban_rights(message)
            )
            buttons = [[Button.inline("Remove", "zombies_remove")]]
            if not can_remove:
                buttons = [[Button.inline("Close", "zombies_close")]]
            await status.edit(
                f"Found `{deleted}` deleted account(s).\n"
                + ("You can remove them." if can_remove else "Only an admin with ban permission can remove them."),
                buttons=buttons,
            )
        else:
            await status.edit("Group is clean; no deleted accounts found.")
        return

    if not await is_administrator(message.sender_id, message):
        return await message.reply("You need to be an admin to remove deleted accounts.")

    status = await message.reply("`Removing deleted accounts…`")
    removed = 0
    skipped_admins = 0
    try:
        async for participant in message.client.iter_participants(message.chat_id):
            if not participant.deleted:
                continue
            try:
                await message.client(
                    EditBannedRequest(message.chat_id, participant.id, BANNED_RIGHTS)
                )
                await message.client(
                    EditBannedRequest(message.chat_id, participant.id, UNBAN_RIGHTS)
                )
                removed += 1
            except ChatAdminRequiredError:
                await status.edit("I need permission to ban members in this group.")
                return
            except UserAdminInvalidError:
                skipped_admins += 1
    except Exception:
        await status.edit("The zombie cleanup was interrupted; please try again later.")
        return

    if removed or skipped_admins:
        result = f"Removed `{removed}` deleted account(s)."
        if skipped_admins:
            result += f" Skipped `{skipped_admins}` admin account(s)."
        await status.edit(result)
    else:
        await status.edit("No deleted accounts were removed.")

@tbot.on(events.CallbackQuery(pattern=r"^zombies_(remove|close)$"))
async def zombies_callback(event):
    if event.pattern_match.group(1) == "close":
        await event.answer("Closed.")
        await event.message.delete()
        return
    if (
        not await is_administrator(event.sender_id, event.message)
        or not await has_ban_rights(event.message, event.sender_id)
        or not await has_ban_rights(event.message)
    ):
        await event.answer("You need to be an admin with ban permission.", alert=True)
        return
    await event.answer("Removing deleted accounts…", alert=True)
    removed = 0
    skipped_admins = 0
    status = await event.message.edit("Removing deleted accounts…")
    try:
        async for participant in event.client.iter_participants(event.chat_id):
            if not participant.deleted:
                continue
            try:
                await event.client(EditBannedRequest(event.chat_id, participant.id, BANNED_RIGHTS))
                await event.client(EditBannedRequest(event.chat_id, participant.id, UNBAN_RIGHTS))
                removed += 1
            except ChatAdminRequiredError:
                await status.edit("I need permission to ban members in this group.")
                return
            except UserAdminInvalidError:
                skipped_admins += 1
    except Exception:
        await status.edit("The zombie cleanup was interrupted; please try again later.")
        return
    result = f"Removed `{removed}` deleted account(s)."
    if skipped_admins:
        result += f" Skipped `{skipped_admins}` admin account(s)."
    await status.edit(result, buttons=[[Button.inline("Close", "zombies_close")]])




__help__ = """
➠ <b>Remove Deleted Accounts:</b>

» /zombies — find deleted accounts in a group
» /zombies clean — remove deleted accounts from a group
"""

__mod_name__ = "ZOMBIES"
