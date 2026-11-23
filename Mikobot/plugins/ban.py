import asyncio
import html
from datetime import datetime, timezone
from uuid import uuid4

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import (
    BAN_STICKER,
    DEV_USERS,
    DRAGONS,
    OWNER_ID,
    chat_data,
    store,
)
from Mikobot.events import on_callback, on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import (
    can_delete,
    check_admin,
    connection_status,
    granted,
    is_user_admin,
    is_user_ban_protected,
    is_user_in_chat,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user_and_text
from Mikobot.plugins.helper_funcs.misc import mention_username
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import gloggable, loggable
from Mikobot.utils.consts import ChatID
from Mikobot.utils.filters import GROUPS
from Mikobot.utils.parser import mention_html

__mod_name__ = "Ban"


@on_message(*disableable(["ban", "sban", "dban"]))
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def ban(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = message.command[1:] if len(message.command) > 1 else []
    user_id, reason = await extract_user_and_text(message, args)
    if user_id is None:
        return await message.reply_text("That is not a valid user ID.")

    SILENT = bool(message.text.startswith("/s"))
    # /dban is the delete-then-act shortcut: the offending message goes too.
    DELETE_MESSAGE = bool(message.text.startswith("/d"))
    if DELETE_MESSAGE and not message.reply_to_message:
        await message.reply_text("Reply to the message you want deleted.")
        return ""

    # Anonymous admins appear as a service account, so confirm via a button.
    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        if SILENT:
            await message.reply_text("/sban does not work for anonymous admins.")
            return log_message
        # Keep the chat title with the pending action to mention the channel after banning.
        try:
            chat_title = message.reply_to_message.sender_chat.title
        except AttributeError:
            chat_title = None
        action_token = uuid4().hex[:8]
        chat_data[f"anon_ban_{action_token}"] = {
            "reason": reason,
            "chat_title": chat_title,
        }
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove Admin.",
                            callback_data=f"bans_{chat.id}=ban={user_id}={action_token}",
                            style=ButtonStyle.DANGER,
                        ),
                    ],
                ]
            ),
        )

        return log_message

    member = await client.get_chat_member(chat.id, user.id)
    if (
        not (
            (
                member.status == ChatMemberStatus.ADMINISTRATOR
                and granted(member, "can_restrict_members")
            )
            or member.status == ChatMemberStatus.OWNER
        )
        and user.id not in DRAGONS
    ):
        await message.reply_text(
            "You do not have permission to ban that user.",
        )
        return log_message

    if user_id == client.me.id:
        await message.reply_text("I cannot ban myself.")
        return log_message

    if user_id is not None and user_id < 0:
        CHAT_SENDER = True
        chat_sender = message.reply_to_message.sender_chat
    else:
        CHAT_SENDER = False
        try:
            member = await client.get_chat_member(chat.id, user_id)
        except RPCError as excp:
            if "user not found" in str(excp.message or excp).lower():
                raise
            elif "invalid user_id" in str(excp.message or excp).lower():
                await message.reply_text("That is not a user.")
                return log_message
            await message.reply_text("I cannot find that user here.")
            return log_message

        if await is_user_ban_protected(chat, user_id, member) and user not in DEV_USERS:
            if user_id == OWNER_ID:
                await message.reply_text("I cannot act against that user.")
            elif user_id in DEV_USERS:
                await message.reply_text("I cannot act against a protected user.")
            elif user_id in DRAGONS:
                await message.reply_text(
                    "I cannot act against a Dragon.",
                )
            else:
                await message.reply_text("This user has immunity and cannot be banned.")
            return log_message

    if SILENT:
        silent = True
        if not await can_delete(chat, client.me.id):
            return ""
    else:
        silent = False

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#{'S' if silent else ''}BANNED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
    )

    reply = "<code>❕</code><b>Ban Event</b>\n"

    if CHAT_SENDER:
        log += f"<b>Channel:</b> {mention_username(chat_sender.username, html.escape(chat_sender.title))}"
        reply += f"<code> </code><b>•  Channel:</b> {mention_username(chat_sender.username, html.escape(chat_sender.title))}"

    else:
        log += f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
        reply += f"<code> </code><b>•  User:</b> {mention_html(member.user.id, member.user.first_name)}"

    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        if CHAT_SENDER:
            await client.ban_chat_member(chat.id, chat_sender.id)
        else:
            await client.ban_chat_member(chat.id, user_id)

        if DELETE_MESSAGE and message.reply_to_message:
            try:
                await message.reply_to_message.delete()
            except RPCError:
                pass

        if silent:
            if message.reply_to_message:
                await message.reply_to_message.delete()
            await message.delete()
            return log

        await client.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )

        if reason:
            reply += f"\n<code> </code><b>•  Reason:</b> \n{html.escape(reason)}"
        await client.send_message(
            chat.id,
            reply,
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        return log

    except RPCError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            if silent:
                return log
            await message.reply_text("User banned.")
            return log
        else:
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.reply_text("That did not work.")

    return log_message


@on_message(*disableable(["tban"]))
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def temp_ban(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = message.command[1:] if len(message.command) > 1 else []
    user_id, reason = await extract_user_and_text(message, args)
    if user_id is None:
        return await message.reply_text("That is not a valid user ID.")

    if not user_id:
        await message.reply_text("That is not a user.")
        return log_message

    try:
        member = await client.get_chat_member(chat.id, user_id)
    except RPCError as excp:
        if "user not found" not in str(excp.message or excp).lower():
            raise
        await message.reply_text("I cannot find that user.")
        return log_message
    if user_id == client.me.id:
        await message.reply_text("I cannot ban myself.")
        return log_message

    if await is_user_ban_protected(chat, user_id, member):
        await message.reply_text("I cannot do that.")
        return log_message

    if not reason:
        await message.reply_text("Specify a ban duration.")
        return log_message

    split_reason = reason.split(None, 1)

    time_val = split_reason[0].lower()
    reason = split_reason[1] if len(split_reason) > 1 else ""
    bantime = await extract_time(message, time_val)

    if not bantime:
        return log_message

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        "#TEMP BANNED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}\n"
        f"<b>Time:</b> {time_val}"
    )
    if reason:
        log += "\n<b>Reason:</b> {}".format(reason)

    try:
        until_dt = datetime.fromtimestamp(bantime, timezone.utc)
        await client.ban_chat_member(chat.id, user_id, until_date=until_dt)
        await client.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        await client.send_message(
            chat.id,
            f"User banned. User {mention_html(member.user.id, member.user.first_name)} "
            f"will be banned for {time_val}.",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        return log

    except RPCError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            await message.reply_text(
                f"User banned. User will be banned for {time_val}.",
            )
            return log
        else:
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.reply_text("I cannot ban that user.")

    return log_message


@on_message(*disableable(["kick", "dkick"]))
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def kick(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user
    log_message = ""
    args = message.command[1:] if len(message.command) > 1 else []
    DELETE_MESSAGE = bool(message.text.startswith("/d"))
    if DELETE_MESSAGE and not message.reply_to_message:
        await message.reply_text("Reply to the message you want deleted.")
        return ""
    user_id, reason = await extract_user_and_text(message, args)
    if user_id is None:
        return await message.reply_text("That is not a valid user ID.")

    if not user_id:
        await message.reply_text("That is not a user.")
        return log_message

    try:
        member = await client.get_chat_member(chat.id, user_id)
    except RPCError as excp:
        if "user not found" not in str(excp.message or excp).lower():
            raise

        await message.reply_text("I cannot find that user.")
        return log_message
    if user_id == client.me.id:
        await message.reply_text("I cannot do that.")
        return log_message

    if await is_user_ban_protected(chat, user_id):
        await message.reply_text("I cannot kick that user.")
        return log_message

    # Unban on the current user = kick.
    try:
        await client.unban_chat_member(chat.id, user_id)
        res = True
    except RPCError:
        res = False

    if DELETE_MESSAGE and message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except RPCError:
            pass

    if res:
        await client.send_sticker(
            chat.id,
            BAN_STICKER,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        await client.send_message(
            chat.id,
            f"Kicked {mention_html(member.user.id, member.user.first_name)}.",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#KICKED\n"
            f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
            f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
        )
        if reason:
            log += f"\n<b>Reason:</b> {html.escape(reason)}"

        return log

    else:
        await message.reply_text("I cannot kick that user.")

    return log_message


@on_message(GROUPS, *disableable("kickme"))
@check_admin(permission="can_restrict_members", is_bot=True)
async def kickme(client, message: Message):
    user_id = message.from_user.id
    if await is_user_admin(message.chat, user_id):
        await message.reply_text("I cannot kick an admin.")
        return

    # Unban on the current user = kick.
    try:
        await client.unban_chat_member(message.chat.id, user_id)
    except RPCError:
        await message.reply_text("I cannot do that.")
        return

    await message.reply_text(
        html.escape("You got the Devil's Kiss, Now die in peace"),
        parse_mode=ParseMode.HTML,
    )


@on_message(*disableable("unban"))
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def unban(client, message: Message) -> str:
    user = message.from_user
    chat = message.chat
    log_message = ""
    args = message.command[1:] if len(message.command) > 1 else []
    user_id, reason = await extract_user_and_text(message, args)
    if user_id is None:
        return await message.reply_text("That is not a valid user ID.")

    if message.from_user and message.from_user.id == ChatID.ANONYMOUS_ADMIN:
        try:
            chat_title = message.reply_to_message.sender_chat.title
        except AttributeError:
            chat_title = None

        action_token = uuid4().hex[:8]
        chat_data[f"anon_ban_{action_token}"] = {
            "reason": reason,
            "chat_title": chat_title,
        }
        await message.reply_text(
            text="You are an anonymous admin.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Click to prove Admin.",
                            callback_data=f"bans_{chat.id}=unban={user_id}={action_token}",
                            style=ButtonStyle.SUCCESS,
                        ),
                    ],
                ]
            ),
        )

        return log_message

    if not user_id:
        await message.reply_text("That is not a user.")
        return log_message

    if user_id == client.me.id:
        await message.reply_text("I cannot unban myself.")
        return log_message

    if user_id is not None and user_id < 0:
        CHAT_SENDER = True
        chat_sender = (
            message.reply_to_message.sender_chat if message.reply_to_message else None
        )
    else:
        CHAT_SENDER = False
        try:
            member = await client.get_chat_member(chat.id, user_id)

            if member.status == ChatMemberStatus.ADMINISTRATOR:
                await message.reply_text("That user is an admin here.")
                return log_message

        except RPCError as excp:
            if "user not found" not in str(excp.message or excp).lower():
                raise
            await message.reply_text("I cannot find that user.")
            return log_message

        if await is_user_in_chat(chat, user_id):
            await message.reply_text("That user is already here.")
            return log_message

    admin_text = mention_html(user.id, user.first_name) if user else "Admin"
    log = f"<b>{html.escape(chat.title)}:</b>\n#UNBANNED\n<b>Admin:</b> {admin_text}\n"

    if CHAT_SENDER:
        target_name = (
            html.escape(chat_sender.title)
            if chat_sender and chat_sender.title
            else str(user_id)
        )
        target_id = chat_sender.id if chat_sender else user_id
        log += f"<b>User:</b> {mention_username(target_id, target_name)}"
        await client.unban_chat_member(chat.id, target_id)
        await message.reply_text("This channel can speak again.")
    else:
        log += f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
        await client.unban_chat_member(chat.id, user_id)
        await message.reply_text("This user can join.")

    if reason:
        log += f"\n<b>Reason:</b> {html.escape(reason)}"

    return log


@on_message(*disableable("roar"))
@connection_status
@gloggable
@check_admin(permission="can_restrict_members", is_bot=True)
async def selfunban(client, message: Message) -> str:
    user = message.from_user
    args = message.command[1:] if len(message.command) > 1 else []
    if not user or user.id not in DRAGONS:
        return

    try:
        chat_id = int(args[0])
    except RPCError, IndexError, ValueError, TypeError:
        await message.reply_text("Provide a valid chat ID.")
        return

    chat = await client.get_chat(chat_id)

    try:
        member = await client.get_chat_member(chat.id, user.id)
    except RPCError as excp:
        if "user not found" in str(excp.message or excp).lower():
            await message.reply_text("I cannot find that user.")
            return
        else:
            raise

    if await is_user_in_chat(chat, user.id):
        await message.reply_text("You are already in this chat.")
        return

    await client.unban_chat_member(chat.id, user.id)
    await message.reply_text("You have been unbanned.")

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#UNBANNED\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    return log


@on_callback(filters.regex(r"^bans_-?\d+=(?:ban|unban)=-?\d+=[0-9a-f]{8}$"))
@loggable
async def bans_callback(client, query: CallbackQuery):
    message = query.message
    chat = message.chat
    log_message = ""
    parts = query.data.removeprefix("bans_").split("=")
    if len(parts) != 4 or parts[1] not in {"ban", "unban"}:
        await query.answer("Invalid callback data.", show_alert=True)
        return log_message

    log_message = ""
    admin_user = query.from_user
    action = parts[1]
    pending = chat_data.get(f"anon_ban_{parts[3]}")
    if not pending:
        await query.answer("This action has expired.", show_alert=True)
        return log_message
    member = await client.get_chat_member(chat.id, admin_user.id)

    if (
        (
            member.status == ChatMemberStatus.ADMINISTRATOR
            and granted(member, "can_restrict_members")
        )
        or member.status == ChatMemberStatus.OWNER
        or admin_user.id in DRAGONS
    ):
        pass
    else:
        await query.answer(
            "You do not have permission to use this action.",
            show_alert=True,
        )
        return log_message

    chat_data.pop(f"anon_ban_{parts[3]}", None)
    await asyncio.to_thread(store.save)
    if action == "ban":
        try:
            user_id = int(parts[2])
        except ValueError:
            await query.answer("Invalid callback data.", show_alert=True)
            return log_message
        reason = pending.get("reason", "")
        chat_name = pending.get("chat_title")

        if user_id == client.me.id:
            await message.edit_text("I cannot ban myself.")
            return log_message

        if isinstance(user_id, str):
            await message.edit_text("That is not a user.")
            return log_message

        if user_id < 0:
            CHAT_SENDER = True
        else:
            CHAT_SENDER = False
            try:
                member = await client.get_chat_member(chat.id, user_id)
            except RPCError as excp:
                err_msg = str(getattr(excp, "message", None) or excp).lower()
                if "user not found" in err_msg:
                    raise
                elif "invalid user_id" in err_msg or "user_id_invalid" in err_msg:
                    await message.edit_text("That is not a user.")
                await message.edit_text("I cannot find that user here.")

                return log_message

            if (
                await is_user_ban_protected(chat, user_id, member)
                and admin_user not in DEV_USERS
            ):
                if user_id == OWNER_ID:
                    await message.edit_text("I cannot act against that user.")
                elif user_id in DEV_USERS:
                    await message.edit_text("I cannot act against a protected user.")
                elif user_id in DRAGONS:
                    await message.edit_text(
                        "I cannot act against a Dragon.",
                    )
                else:
                    await message.edit_text(
                        "This user has immunity and cannot be banned."
                    )
                return log_message

        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#BANNED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}\n"
        )

        reply = "<code>❕</code><b>Ban Event</b>\n"

        if CHAT_SENDER:
            log += f"<b>Channel:</b> {html.escape(chat_name)}"
            reply += f"<code> </code><b>•  Channel:</b> {html.escape(chat_name)}"

        else:
            log += (
                f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
            )
            reply += f"<code> </code><b>•  User:</b> {mention_html(member.user.id, member.user.first_name)}"

        if reason:
            log += "\n<b>Reason:</b> {}".format(reason)

        try:
            await client.ban_chat_member(chat.id, user_id)

            await client.send_sticker(
                chat.id,
                BAN_STICKER,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )

            if reason:
                reply += f"\n<code> </code><b>•  Reason:</b> \n{html.escape(reason)}"
            await client.send_message(
                chat.id,
                reply,
                parse_mode=ParseMode.HTML,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )
            await query.answer("User banned.")
            return log

        except RPCError as excp:
            if "reply message not found" in str(excp.message or excp).lower():
                # Do not reply
                await message.edit_text("User banned.")
                return log
            LOGGER.exception(
                "ERROR banning user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.edit_text("That did not work.")

        return log_message

    elif action == "unban":
        try:
            user_id = int(parts[2])
        except ValueError:
            await query.answer("Invalid callback data.", show_alert=True)
            return log_message
        reason = pending.get("reason", "")

        if isinstance(user_id, str):
            await message.edit_text("That is not a user.")
            return log_message

        if user_id == client.me.id:
            await message.edit_text("I cannot unban myself.")
            return log_message

        if user_id < 0:
            CHAT_SENDER = True
            chat_title = pending.get("chat_title")
        else:
            CHAT_SENDER = False

            try:
                member = await client.get_chat_member(chat.id, user_id)
            except RPCError as excp:
                if "user not found" not in str(excp.message or excp).lower():
                    raise
                await message.edit_text("I cannot find that user.")
                return log_message

            if await is_user_in_chat(chat, user_id):
                await message.edit_text("That user is already here.")
                return log_message

        log = (
            f"<b>{html.escape(chat.title)}:</b>\n"
            f"#UNBANNED\n"
            f"<b>Admin:</b> {mention_html(admin_user.id, admin_user.first_name)}\n"
        )

        if CHAT_SENDER:
            log += f"<b>User:</b> {html.escape(chat_title)}"
            await client.unban_chat_member(chat.id, user_id)
            await message.reply_text("This channel can speak again.")
        else:
            log += (
                f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
            )
            await client.unban_chat_member(chat.id, user_id)
            await message.reply_text("This user can join.")

        if reason:
            log += f"\n<b>Reason:</b> {html.escape(reason)}"

        await query.answer("User unbanned.")
        return log


__help__ = """
Commands:
/kickme: Kick yourself from the group.

Admin only:
/ban <userhandle>: Ban a user or channel. Accepts a handle or a reply.
/sban <userhandle>: Silently ban a user. Deletes the command and the replied message, and sends no reply. Accepts a handle or a reply.
/dban <userhandle>: Delete the replied message and ban the user. Requires a reply.
/dkick <userhandle>: Delete the replied message and kick the user. Requires a reply.
/tban <userhandle> x(m/h/d): Ban a user for x time. Units: m minutes, h hours, d days. Accepts a handle or a reply.
/unban <userhandle>: Unban a user or channel. Accepts a handle or a reply.
/kick <userhandle>: Kick a user from the group. Accepts a handle or a reply.

Channels can be banned or unbanned only by replying to their message, not by username.
"""
