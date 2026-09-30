import html
from datetime import datetime, timezone

from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    MenuButtonCommands,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from Mikobot import bot, dp
from Mikobot.plugins.helper_funcs.chat_status import check_admin, connection_status
from Mikobot.utils.gate import chain


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
        return int(datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as exc:
        raise ValueError("Expiry must use YYYY-MM-DD HH:MM UTC.") from exc


async def _reply_error(message: Message, error: Exception) -> None:
    if isinstance(error, TelegramBadRequest):
        await message.answer(f"Telegram rejected this request: {error.message}")
    elif isinstance(error, TelegramAPIError):
        await message.answer("Telegram could not complete this request.")
    else:
        await message.answer(f"Unable to complete the request: {error}")


@connection_status
async def chatinfo(message: Message, command: CommandObject) -> None:
    chat = await bot.get_chat(message.chat.id)
    count = await bot.get_chat_member_count(chat.id)
    admins = await bot.get_chat_administrators(chat.id)
    description = html.escape(getattr(chat, "description", None) or "None")
    text = (
        f"<b>{html.escape(chat.title or chat.type.title())}</b>\n"
        f"ID: <code>{chat.id}</code>\nType: <code>{chat.type}</code>\n"
        f"Username: {('@' + chat.username) if chat.username else 'None'}\n"
        f"Members: <code>{count}</code>\nAdministrators: <code>{len(admins)}</code>\n"
        f"Description: {description}\nForum: {'Yes' if getattr(chat, 'is_forum', False) else 'No'}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@connection_status
async def members(message: Message, command: CommandObject) -> None:
    count = await bot.get_chat_member_count(message.chat.id)
    await message.answer(f"This chat has <code>{count}</code> members.", parse_mode=ParseMode.HTML)


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def invite_manage(message: Message, command: CommandObject) -> None:
    if not _group_only(message):
        return await message.answer("Use this command in a group or supergroup.")
    chat_id, args = message.chat.id, command.args
    if not args or args[0].lower() == "export":
        await message.answer(await bot.export_chat_invite_link(chat_id))
        return
    action = args[0].lower()
    try:
        if action == "create":
            link = await bot.create_chat_invite_link(chat_id, name=args[1] if len(args) > 1 else None, member_limit=int(args[2]) if len(args) > 2 else None, expire_date=_expiry(args[3] if len(args) > 3 else None))
        elif action == "edit" and len(args) >= 2:
            link = await bot.edit_chat_invite_link(chat_id, args[1], name=args[2] if len(args) > 2 else None, member_limit=int(args[3]) if len(args) > 3 else None, expire_date=_expiry(args[4] if len(args) > 4 else None))
        elif action == "revoke" and len(args) >= 2:
            link = await bot.revoke_chat_invite_link(chat_id, args[1])
        else:
            await message.answer("Usage: /invitelink create|edit|revoke ...")
            return
        await message.answer(f"Invite link: {link.invite_link}")
    except (ValueError, TelegramAPIError) as error:
        await _reply_error(message, error)


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def join_requests(message: Message, command: CommandObject) -> None:
    if len(command.args) != 2 or command.args[0].lower() not in {"approve", "decline"}:
        return await message.answer("Usage: /joins approve|decline <user_id>")
    try:
        user_id, action = _user_id(command.args[1]), command.args[0].lower()
        method = bot.approve_chat_join_request if action == "approve" else bot.decline_chat_join_request
        await method(message.chat.id, user_id)
        await message.answer(f"Join request {action}d.")
    except (ValueError, TelegramAPIError) as error:
        await _reply_error(message, error)



@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_metadata(message: Message, command: CommandObject) -> None:
    args = command.args
    if not args:
        return await message.answer("Usage: /setchat <title|description|description-> [text]")
    try:
        action = args[0].lower()
        if action == "title" and len(args) > 1:
            await bot.set_chat_title(message.chat.id, " ".join(args[1:]))
        elif action == "description" and len(args) > 1:
            await bot.set_chat_description(message.chat.id, " ".join(args[1:]))
        elif action == "description-":
            await bot.set_chat_description(message.chat.id)
        else:
            await message.answer("Usage: /setchat <title|description|description-> [text]")
            return
        await message.answer("Chat metadata updated.")
    except TelegramAPIError as error:
        await _reply_error(message, error)


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_photo(message: Message, command: CommandObject) -> None:
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.answer("Reply to a photo to set it as the chat photo.")
    await bot.set_chat_photo(message.chat.id, message.reply_to_message.photo[-1].file_id)
    await message.answer("Chat photo updated.")


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def delete_chat_photo(message: Message, command: CommandObject) -> None:
    await bot.delete_chat_photo(message.chat.id)
    await message.answer("Chat photo deleted.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def topics(message: Message, command: CommandObject) -> None:
    chat, args = message.chat, command.args
    if not chat.is_forum:
        return await message.answer("This chat is not a forum.")
    if not args:
        return await message.answer("Usage: /topic create|edit|close|reopen|delete <name|thread_id>")
    try:
        action = args[0].lower()
        if action == "create" and len(args) > 1:
            topic = await bot.create_forum_topic(chat.id, " ".join(args[1:]))
            result = f"Topic created: <code>{topic.name}</code>"
        elif action == "edit" and len(args) > 2:
            await bot.edit_forum_topic(chat.id, int(args[1]), " ".join(args[2:]))
            result = "Topic updated."
        elif action in {"close", "reopen", "delete"} and len(args) > 1:
            await getattr(bot, f"{action}_forum_topic")(chat.id, int(args[1]))
            result = f"Topic {action}d."
        elif action == "general" and len(args) > 1 and args[1].lower() in {"close", "reopen", "unpinall"}:
            action_name = args[1].lower()
            if action_name == "unpinall":
                await bot.unpin_all_general_forum_topic_messages(chat.id)
            else:
                await getattr(bot, f"{action_name}_general_forum_topic")(chat.id)
            result = f"General topic {action_name} completed."
        else:
            await message.answer("Usage: /topic create|edit|close|reopen|delete <name|thread_id>")
            return
        await message.answer(result, parse_mode=ParseMode.HTML)
    except (ValueError, TelegramAPIError) as error:
        await _reply_error(message, error)


@connection_status
async def menu_button(message: Message, command: CommandObject) -> None:
    chat_id = message.chat.id
    if not command.args:
        button = await bot.get_chat_menu_button(chat_id)
        await message.answer(f"Menu button: {button.model_dump() if button else 'None'}")
        return
    action = command.args[0].lower()
    if action == "commands":
        await bot.set_chat_menu_button(chat_id, MenuButtonCommands())
    elif action == "default":
        await bot.set_chat_menu_button(chat_id, MenuButtonDefault())
    elif action == "webapp" and len(command.args) > 1:
        await bot.set_chat_menu_button(
            chat_id,
            # aiogram requires text on MenuButtonWebApp; PTB defaulted it to
            # the URL, so keep that rather than inventing a label.
            MenuButtonWebApp(
                text=command.args[1],
                web_app=WebAppInfo(url=command.args[1]),
            ),
        )
    else:
        await message.answer("Usage: /menubutton [commands|default|webapp <url>]")
        return
    await message.answer("Menu button updated.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def sticker_set(message: Message, command: CommandObject) -> None:
    if len(command.args) == 2 and command.args[0].lower() == "set":
        await bot.set_chat_sticker_set(message.chat.id, command.args[1])
        await message.answer("Sticker set updated.")
    elif command.args and command.args[0].lower() == "delete":
        await bot.delete_chat_sticker_set(message.chat.id)
        await message.answer("Sticker set deleted.")
    else:
        await message.answer("Usage: /stickerset set <name> | /stickerset delete")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def clear_reactions(message: Message, command: CommandObject) -> None:
    if not message.reply_to_message:
        return await message.answer("Reply to a message to clear all reactions.")
    try:
        await bot.delete_all_message_reactions(
            message.chat.id, message.reply_to_message.message_id
        )
    except TelegramAPIError as error:
        await _reply_error(message, error)
        return
    await message.answer("All reactions were removed.")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def delete_reaction(message: Message, command: CommandObject) -> None:
    if not message.reply_to_message:
        return await message.answer(
            "Reply to a message and optionally provide a user ID to remove their reaction."
        )
    if len(command.args) > 1:
        return await message.answer("Usage: /deletereaction [user_id]")
    user_id = None
    if command.args:
        try:
            user_id = _user_id(command.args[0])
        except ValueError as error:
            await _reply_error(message, error)
            return
    try:
        await bot.delete_message_reaction(
            message.chat.id,
            message.reply_to_message.message_id,
            user_id=user_id,
        )
    except TelegramAPIError as error:
        await _reply_error(message, error)
        return
    target = f" for user `{user_id}`" if user_id is not None else ""
    await message.answer(f"Reaction removed{target}.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def member_tag(message: Message, command: CommandObject) -> None:
    if len(command.args) not in {1, 2}:
        return await message.answer("Usage: /membertag <user_id> [tag|remove]")
    try:
        user_id = _user_id(command.args[0])
        tag = None if len(command.args) == 1 or command.args[1].lower() == "remove" else command.args[1]
        await bot.set_chat_member_tag(message.chat.id, user_id, tag)
        await message.answer("Member tag updated.")
    except (ValueError, TelegramAPIError) as error:
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
    dp.message.register(chain(callback), Command(command_name))

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
