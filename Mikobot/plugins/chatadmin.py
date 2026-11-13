import html
from datetime import datetime, timezone

from pyrogram import filters, raw
from pyrogram.enums import ChatMembersFilter, ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    MenuButtonCommands,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin, connection_status


def _group_only(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def _user_id(value: str) -> int:
    value = value.strip()
    if value.startswith("@"):
        raise ValueError("Use a numeric user ID for join requests and tags.")
    return int(value)


def _expiry(value: str | None) -> int | None:
    if not value or value.lower() in {"none", "never"}:
        return None
    try:
        return int(
            datetime.strptime(value, "%Y-%m-%d %H:%M")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError as exc:
        raise ValueError("Expiry must use YYYY-MM-DD HH:MM UTC.") from exc


async def _reply_error(message: Message, error: Exception) -> None:
    if isinstance(error, RPCError):
        await message.reply_text(f"Telegram rejected this request: {error.message}")
    else:
        await message.reply_text(f"Unable to complete the request: {error}")


@connection_status
async def chatinfo(client, message: Message) -> None:
    chat = await client.get_chat(message.chat.id)
    count = await client.get_chat_members_count(chat.id)
    admins = []
    async for a in client.get_chat_members(
        chat.id, filter=ChatMembersFilter.ADMINISTRATORS
    ):
        admins.append(a)
    description = html.escape(getattr(chat, "description", None) or "None")
    text = (
        f"<b>{html.escape(chat.title or chat.type.title())}</b>\n"
        f"ID: <code>{chat.id}</code>\nType: <code>{chat.type}</code>\n"
        f"Username: {('@' + chat.username) if chat.username else 'None'}\n"
        f"Members: <code>{count}</code>\nAdministrators: <code>{len(admins)}</code>\n"
        f"Description: {description}\nForum: {'Yes' if getattr(chat, 'is_forum', False) else 'No'}"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)


@connection_status
async def members(client, message: Message) -> None:
    count = await client.get_chat_members_count(message.chat.id)
    await message.reply_text(
        f"This chat has <code>{count}</code> members.", parse_mode=ParseMode.HTML
    )


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def invite_manage(client, message: Message) -> None:
    if not _group_only(message):
        return await message.reply_text("Use this command in a group or supergroup.")
    chat_id = message.chat.id
    args = message.command[1:] if len(message.command) > 1 else []
    if not args or args[0].lower() == "export":
        await message.reply_text(await client.export_chat_invite_link(chat_id))
        return
    action = args[0].lower()
    try:
        if action == "create":
            link = await client.create_invite_link(
                chat_id,
                name=args[1] if len(args) > 1 else None,
                member_limit=int(args[2]) if len(args) > 2 else None,
                expire_date=_expiry(args[3] if len(args) > 3 else None),
            )
        elif action == "edit" and len(args) >= 2:
            link = await client.edit_invite_link(
                chat_id,
                args[1],
                name=args[2] if len(args) > 2 else None,
                member_limit=int(args[3]) if len(args) > 3 else None,
                expire_date=_expiry(args[4] if len(args) > 4 else None),
            )
        elif action == "revoke" and len(args) >= 2:
            link = await client.revoke_invite_link(chat_id, args[1])
        else:
            await message.reply_text("Usage: /invitelink create|edit|revoke ...")
            return
        await message.reply_text(f"Invite link: {link.invite_link}")
    except (ValueError, RPCError) as error:
        await _reply_error(message, error)


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def join_requests(client, message: Message) -> None:
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) != 2 or args[0].lower() not in {"approve", "decline"}:
        return await message.reply_text("Usage: /joins approve|decline <user_id>")
    try:
        user_id, action = _user_id(args[1]), args[0].lower()
        method = (
            client.approve_chat_join_request
            if action == "approve"
            else client.decline_chat_join_request
        )
        await method(message.chat.id, user_id)
        await message.reply_text(f"Join request {action}d.")
    except (ValueError, RPCError) as error:
        await _reply_error(message, error)


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_metadata(client, message: Message) -> None:
    args = message.command[1:] if len(message.command) > 1 else []
    if not args:
        return await message.reply_text(
            "Usage: /setchat <title|description|description-> [text]"
        )
    try:
        action = args[0].lower()
        if action == "title" and len(args) > 1:
            await client.set_chat_title(message.chat.id, " ".join(args[1:]))
        elif action == "description" and len(args) > 1:
            await client.set_chat_description(message.chat.id, " ".join(args[1:]))
        elif action == "description-":
            await client.set_chat_description(message.chat.id)
        else:
            await message.reply_text(
                "Usage: /setchat <title|description|description-> [text]"
            )
            return
        await message.reply_text("Chat metadata updated.")
    except RPCError as error:
        await _reply_error(message, error)


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_photo(client, message: Message) -> None:
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("Reply to a photo to set it as the chat photo.")
    await client.set_chat_photo(
        message.chat.id, photo=message.reply_to_message.photo.file_id
    )
    await message.reply_text("Chat photo updated.")


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def delete_chat_photo(client, message: Message) -> None:
    await client.delete_chat_photo(message.chat.id)
    await message.reply_text("Chat photo deleted.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def topics(client, message: Message) -> None:
    chat = message.chat
    args = message.command[1:] if len(message.command) > 1 else []
    if not chat.is_forum:
        return await message.reply_text("This chat is not a forum.")
    if not args:
        return await message.reply_text(
            "Usage: /topic create|edit|close|reopen|delete <name|thread_id>"
        )
    try:
        action = args[0].lower()
        if action == "create" and len(args) > 1:
            topic = await client.create_forum_topic(chat.id, " ".join(args[1:]))
            result = f"Topic created: <code>{topic.name}</code>"
        elif action == "edit" and len(args) > 2:
            await client.edit_forum_topic(chat.id, int(args[1]), " ".join(args[2:]))
            result = "Topic updated."
        elif action in {"close", "reopen", "delete"} and len(args) > 1:
            await getattr(client, f"{action}_forum_topic")(chat.id, int(args[1]))
            result = f"Topic {action}d."
        elif (
            action == "general"
            and len(args) > 1
            and args[1].lower() in {"close", "reopen", "unpinall"}
        ):
            action_name = args[1].lower()
            if action_name == "unpinall":
                await client.unpin_all_general_forum_topic_messages(chat.id)
            else:
                await getattr(client, f"{action_name}_general_forum_topic")(chat.id)
            result = f"General topic {action_name} completed."
        else:
            await message.reply_text(
                "Usage: /topic create|edit|close|reopen|delete <name|thread_id>"
            )
            return
        await message.reply_text(result, parse_mode=ParseMode.HTML)
    except (ValueError, RPCError) as error:
        await _reply_error(message, error)


@connection_status
async def menu_button(client, message: Message) -> None:
    chat_id = message.chat.id
    args = message.command[1:] if len(message.command) > 1 else []
    if not args:
        button = await client.get_chat_menu_button(chat_id)
        await message.reply_text(f"Menu button: {button}")
        return
    action = args[0].lower()
    if action == "commands":
        await client.set_chat_menu_button(chat_id, MenuButtonCommands())
    elif action == "default":
        await client.set_chat_menu_button(chat_id, MenuButtonDefault())
    elif action == "webapp" and len(args) > 1:
        await client.set_chat_menu_button(
            chat_id,
            MenuButtonWebApp(
                text=args[1],
                web_app=WebAppInfo(url=args[1]),
            ),
        )
    else:
        await message.reply_text("Usage: /menubutton [commands|default|webapp <url>]")
        return
    await message.reply_text("Menu button updated.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def sticker_set(client, message: Message) -> None:
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) == 2 and args[0].lower() == "set":
        try:
            peer = await client.resolve_peer(message.chat.id)
            await client.invoke(
                raw.functions.channels.SetStickers(
                    channel=peer,
                    stickerset=raw.types.InputStickerSetShortName(short_name=args[1]),
                )
            )
            await message.reply_text("Sticker set updated.")
        except RPCError as error:
            await _reply_error(message, error)
    elif args and args[0].lower() == "delete":
        try:
            peer = await client.resolve_peer(message.chat.id)
            await client.invoke(
                raw.functions.channels.SetStickers(
                    channel=peer,
                    stickerset=raw.types.InputStickerSetEmpty(),
                )
            )
            await message.reply_text("Sticker set deleted.")
        except RPCError as error:
            await _reply_error(message, error)
    else:
        await message.reply_text("Usage: /stickerset set <name> | /stickerset delete")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def clear_reactions(client, message: Message) -> None:
    if not message.reply_to_message:
        return await message.reply_text("Reply to a message to clear all reactions.")
    try:
        peer = await client.resolve_peer(message.chat.id)
        res = await client.invoke(
            raw.functions.messages.GetMessageReactionsList(
                peer=peer,
                id=message.reply_to_message.id,
                limit=100,
            )
        )
        if hasattr(res, "reactions"):
            for r in res.reactions:
                p = await client.resolve_peer(r.peer_id)
                await client.invoke(
                    raw.functions.messages.DeleteParticipantReaction(
                        peer=peer,
                        msg_id=message.reply_to_message.id,
                        participant=p,
                    )
                )
    except RPCError as error:
        await _reply_error(message, error)
        return
    await message.reply_text("All reactions were removed.")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def delete_reaction(client, message: Message) -> None:
    if not message.reply_to_message:
        return await message.reply_text(
            "Reply to a message and optionally provide a user ID to remove their reaction."
        )
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) > 1:
        return await message.reply_text("Usage: /deletereaction [user_id]")
    user_id = None
    if args:
        try:
            user_id = _user_id(args[0])
        except ValueError as error:
            await _reply_error(message, error)
            return
    elif message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
    try:
        await client.delete_message_reaction(
            message.chat.id,
            message.reply_to_message.id,
            user_id=user_id,
        )
    except RPCError as error:
        await _reply_error(message, error)
        return
    target = f" for user `{user_id}`" if user_id is not None else ""
    await message.reply_text(f"Reaction removed{target}.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def member_tag(client, message: Message) -> None:
    args = message.command[1:] if len(message.command) > 1 else []
    if len(args) not in {1, 2}:
        return await message.reply_text("Usage: /membertag <user_id> [tag|remove]")
    try:
        user_id = _user_id(args[0])
        tag = None if len(args) == 1 or args[1].lower() == "remove" else args[1]
        await client.set_chat_member_tag(message.chat.id, user_id, tag)
        await message.reply_text("Member tag updated.")
    except (ValueError, RPCError) as error:
        await _reply_error(message, error)


COMMANDS = {
    "chatinfo": chatinfo,
    "members": members,
    "invitelink": invite_manage,
    "joins": join_requests,
    "setchat": set_chat_metadata,
    "setchatphoto": set_chat_photo,
    "delchatphoto": delete_chat_photo,
    "topic": topics,
    "menubutton": menu_button,
    "stickerset": sticker_set,
    "membertag": member_tag,
    "clearreactions": clear_reactions,
    "deleteallreactions": clear_reactions,
    "deletereaction": delete_reaction,
}
for command_name, callback in COMMANDS.items():
    on_message(filters.command(command_name), chained=True)(callback)

__help__ = """
➠ <b>Chat management:</b>
» /chatinfo — chat information and member count
» /members — member count
» /invitelink export|create|edit|revoke — invite-link management
» /joins approve|decline &lt;user_id&gt; — join requests
» /setchat title|description|description- — chat metadata
» /setchatphoto, /delchatphoto — chat photo
» /topic create|edit|close|reopen|delete — forum topics
» /menubutton commands|default|webapp &lt;url&gt; — menu button
» /stickerset set &lt;name&gt;|delete — chat sticker set
» /membertag &lt;user_id&gt; [tag|remove] — member tag
» /clearreactions or /deleteallreactions — remove all reactions from a replied message
» /deletereaction [user_id] — remove a user reaction from a replied message
"""

__mod_name__ = "CHAT ADMIN"
