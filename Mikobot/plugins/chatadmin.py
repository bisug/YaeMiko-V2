import html
from datetime import datetime, timezone

from telegram import MenuButtonCommands, MenuButtonDefault, MenuButtonWebApp, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import CommandHandler, ContextTypes

from Mikobot import function
from Mikobot.plugins.helper_funcs.chat_status import check_admin, connection_status


def _group_only(update: Update) -> bool:
    return update.effective_chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


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


async def _reply_error(update: Update, error: Exception) -> None:
    if isinstance(error, BadRequest):
        await update.effective_message.reply_text(f"Telegram rejected this request: {error.message}")
    elif isinstance(error, TelegramError):
        await update.effective_message.reply_text("Telegram could not complete this request.")
    else:
        await update.effective_message.reply_text(f"Unable to complete the request: {error}")


@connection_status
async def chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = await context.bot.get_chat(update.effective_chat.id)
    count = await context.bot.get_chat_member_count(chat.id)
    admins = await context.bot.get_chat_administrators(chat.id)
    description = html.escape(getattr(chat, "description", None) or "None")
    text = (
        f"<b>{html.escape(chat.title or chat.type.title())}</b>\n"
        f"ID: <code>{chat.id}</code>\nType: <code>{chat.type}</code>\n"
        f"Username: {('@' + chat.username) if chat.username else 'None'}\n"
        f"Members: <code>{count}</code>\nAdministrators: <code>{len(admins)}</code>\n"
        f"Description: {description}\nForum: {'Yes' if getattr(chat, 'is_forum', False) else 'No'}"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


@connection_status
async def members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = await context.bot.get_chat_member_count(update.effective_chat.id)
    await update.effective_message.reply_text(f"This chat has <code>{count}</code> members.", parse_mode=ParseMode.HTML)


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def invite_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _group_only(update):
        return await update.effective_message.reply_text("Use this command in a group or supergroup.")
    bot, chat_id, args = context.bot, update.effective_chat.id, context.args
    if not args or args[0].lower() == "export":
        await update.effective_message.reply_text(await bot.export_chat_invite_link(chat_id))
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
            await update.effective_message.reply_text("Usage: /invitelink create|edit|revoke ...")
            return
        await update.effective_message.reply_text(f"Invite link: {link.invite_link}")
    except (ValueError, TelegramError) as error:
        await _reply_error(update, error)


@connection_status
@check_admin(permission="can_invite_users", is_both=True)
async def join_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2 or context.args[0].lower() not in {"approve", "decline"}:
        return await update.effective_message.reply_text("Usage: /joins approve|decline <user_id>")
    try:
        user_id, action = _user_id(context.args[1]), context.args[0].lower()
        method = context.bot.approve_chat_join_request if action == "approve" else context.bot.decline_chat_join_request
        await method(update.effective_chat.id, user_id)
        await update.effective_message.reply_text(f"Join request {action}d.")
    except (ValueError, TelegramError) as error:
        await _reply_error(update, error)



@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_metadata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        return await update.effective_message.reply_text("Usage: /setchat <title|description|description-> [text]")
    try:
        action = args[0].lower()
        if action == "title" and len(args) > 1:
            await context.bot.set_chat_title(update.effective_chat.id, " ".join(args[1:]))
        elif action == "description" and len(args) > 1:
            await context.bot.set_chat_description(update.effective_chat.id, " ".join(args[1:]))
        elif action == "description-":
            await context.bot.set_chat_description(update.effective_chat.id)
        else:
            await update.effective_message.reply_text("Usage: /setchat <title|description|description-> [text]")
            return
        await update.effective_message.reply_text("Chat metadata updated.")
    except TelegramError as error:
        await _reply_error(update, error)


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def set_chat_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("Reply to a photo to set it as the chat photo.")
    await context.bot.set_chat_photo(update.effective_chat.id, message.reply_to_message.photo[-1].file_id)
    await message.reply_text("Chat photo updated.")


@connection_status
@check_admin(permission="can_change_info", is_both=True)
async def delete_chat_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.delete_chat_photo(update.effective_chat.id)
    await update.effective_message.reply_text("Chat photo deleted.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, args = update.effective_chat, context.args
    if not chat.is_forum:
        return await update.effective_message.reply_text("This chat is not a forum.")
    if not args:
        return await update.effective_message.reply_text("Usage: /topic create|edit|close|reopen|delete <name|thread_id>")
    try:
        action = args[0].lower()
        if action == "create" and len(args) > 1:
            topic = await context.bot.create_forum_topic(chat.id, " ".join(args[1:]))
            result = f"Topic created: <code>{topic.name}</code>"
        elif action == "edit" and len(args) > 2:
            await context.bot.edit_forum_topic(chat.id, int(args[1]), " ".join(args[2:]))
            result = "Topic updated."
        elif action in {"close", "reopen", "delete"} and len(args) > 1:
            await getattr(context.bot, f"{action}_forum_topic")(chat.id, int(args[1]))
            result = f"Topic {action}d."
        elif action == "general" and len(args) > 1 and args[1].lower() in {"close", "reopen", "unpinall"}:
            action_name = args[1].lower()
            if action_name == "unpinall":
                await context.bot.unpin_all_general_forum_topic_messages(chat.id)
            else:
                await getattr(context.bot, f"{action_name}_general_forum_topic")(chat.id)
            result = f"General topic {action_name} completed."
        else:
            await update.effective_message.reply_text("Usage: /topic create|edit|close|reopen|delete <name|thread_id>")
            return
        await update.effective_message.reply_text(result, parse_mode=ParseMode.HTML)
    except (ValueError, TelegramError) as error:
        await _reply_error(update, error)


@connection_status
async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        button = await context.bot.get_chat_menu_button(chat_id)
        await update.effective_message.reply_text(f"Menu button: {button.to_dict() if button else 'None'}")
        return
    action = context.args[0].lower()
    if action == "commands":
        await context.bot.set_chat_menu_button(chat_id, MenuButtonCommands())
    elif action == "default":
        await context.bot.set_chat_menu_button(chat_id, MenuButtonDefault())
    elif action == "webapp" and len(context.args) > 1:
        await context.bot.set_chat_menu_button(chat_id, MenuButtonWebApp(context.args[1], context.args[1]))
    else:
        await update.effective_message.reply_text("Usage: /menubutton [commands|default|webapp <url>]")
        return
    await update.effective_message.reply_text("Menu button updated.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def sticker_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) == 2 and context.args[0].lower() == "set":
        await context.bot.set_chat_sticker_set(update.effective_chat.id, context.args[1])
        await update.effective_message.reply_text("Sticker set updated.")
    elif context.args and context.args[0].lower() == "delete":
        await context.bot.delete_chat_sticker_set(update.effective_chat.id)
        await update.effective_message.reply_text("Sticker set deleted.")
    else:
        await update.effective_message.reply_text("Usage: /stickerset set <name> | /stickerset delete")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def clear_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        return await message.reply_text("Reply to a message to clear all reactions.")
    try:
        await context.bot.delete_all_message_reactions(
            update.effective_chat.id, message.reply_to_message.message_id
        )
    except TelegramError as error:
        await _reply_error(update, error)
        return
    await message.reply_text("All reactions were removed.")


@connection_status
@check_admin(permission="can_delete_messages", is_both=True)
async def delete_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message.reply_to_message:
        return await message.reply_text(
            "Reply to a message and optionally provide a user ID to remove their reaction."
        )
    if len(context.args) > 1:
        return await message.reply_text("Usage: /deletereaction [user_id]")
    user_id = None
    if context.args:
        try:
            user_id = _user_id(context.args[0])
        except ValueError as error:
            await _reply_error(update, error)
            return
    try:
        await context.bot.delete_message_reaction(
            update.effective_chat.id,
            message.reply_to_message.message_id,
            user_id=user_id,
        )
    except TelegramError as error:
        await _reply_error(update, error)
        return
    target = f" for user `{user_id}`" if user_id is not None else ""
    await message.reply_text(f"Reaction removed{target}.")


@connection_status
@check_admin(permission="can_manage_topics", is_both=True)
async def member_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) not in {1, 2}:
        return await update.effective_message.reply_text("Usage: /membertag <user_id> [tag|remove]")
    try:
        user_id = _user_id(context.args[0])
        tag = None if len(context.args) == 1 or context.args[1].lower() == "remove" else context.args[1]
        await context.bot.set_chat_member_tag(update.effective_chat.id, user_id, tag)
        await update.effective_message.reply_text("Member tag updated.")
    except (ValueError, TelegramError) as error:
        await _reply_error(update, error)


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
for command, callback in COMMANDS.items():
    function(CommandHandler(command, callback, block=False))

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
