import html
from datetime import datetime, timezone

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import Chat, ChatPermissions, Message

from Mikobot import LOGGER
from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import (
    check_admin,
    connection_status,
    is_user_admin,
)
from Mikobot.plugins.helper_funcs.extraction import extract_user, extract_user_and_text
from Mikobot.plugins.helper_funcs.string_handling import extract_time
from Mikobot.plugins.log_channel import loggable
from Mikobot.utils.parser import mention_html

RESTRICTED_OR_MEMBER = (ChatMemberStatus.RESTRICTED, ChatMemberStatus.MEMBER)
LEFT_OR_BANNED = ("left", "kicked")


async def check_user(user_id: int, client, chat: Chat) -> str | None:
    if not user_id:
        reply = (
            "You don't seem to be referring to a user or the ID specified is"
            " incorrect.."
        )
        return reply

    try:
        await client.get_chat_member(chat.id, user_id)
    except RPCError:
        return "I can't seem to find this user"

    if user_id == client.id:
        reply = "I'm not gonna MUTE myself, How high are you?"
        return reply

    if await is_user_admin(chat, user_id):
        reply = "Sorry can't do that, this user is admin here."
        return reply

    return None


async def _delete_replied(message: Message) -> None:
    """Remove the offending message for the /d-prefixed variants.

    These are reply-only shortcuts, so without a reply there is nothing to
    delete and the caller should stop before acting on the wrong message.
    """
    cmd = message.command[0].lower() if message.command else ""
    if not cmd.startswith("d"):
        return
    if not message.reply_to_message:
        await message.reply_text("Reply to the message you want deleted with that.")
        raise _StopCommand
    try:
        await message.reply_to_message.delete()
    except RPCError:
        pass


class _StopCommand(Exception):
    """Raised to abandon a command once its precondition fails."""


@on_message(filters.command(["mute", "dmute"]), chained=True)
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def mute(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user

    try:
        await _delete_replied(message)
    except _StopCommand:
        return ""

    args = message.command[1:] if len(message.command) > 1 else []
    user_id, reason = await extract_user_and_text(message, args)
    reply = await check_user(user_id, client, chat)

    if reply:
        await message.reply_text(reply)
        return ""

    member = await client.get_chat_member(chat.id, user_id)

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#MUTE\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
    )

    if reason:
        log += f"\n<b>Reason:</b> {html.escape(reason)}"

    if member.status in RESTRICTED_OR_MEMBER:
        chat_permissions = ChatPermissions(can_send_messages=False)
        await client.restrict_chat_member(chat.id, user_id, chat_permissions)
        await client.send_message(
            chat.id,
            f"Muted <b>{html.escape(member.user.first_name)}</b> with no expiration"
            " date!",
            parse_mode=ParseMode.HTML,
            message_thread_id=message.message_thread_id if chat.is_forum else None,
        )
        return log

    else:
        await message.reply_text("This user is already muted!")

    return ""


@on_message(filters.command("unmute"), chained=True)
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def unmute(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user

    args = message.command[1:] if len(message.command) > 1 else []
    user_id = await extract_user(message, args)
    if not user_id:
        await message.reply_text(
            "You'll need to either give me a username to unmute, or reply to someone"
            " to be unmuted.",
        )
        return ""

    member = await client.get_chat_member(chat.id, int(user_id))

    if member.status not in LEFT_OR_BANNED:
        if member.status != ChatMemberStatus.RESTRICTED:
            await message.reply_text("This user already has the right to speak.")
        else:
            chat_permissions = ChatPermissions(
                can_send_messages=True,
                can_invite_users=True,
                can_send_polls=True,
                can_change_info=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
            try:
                await client.restrict_chat_member(
                    chat.id, int(user_id), chat_permissions
                )
            except RPCError:
                pass
            await client.send_message(
                chat.id,
                f"I shall allow <b>{html.escape(member.user.first_name)}</b> to text!",
                parse_mode=ParseMode.HTML,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )
            return (
                f"<b>{html.escape(chat.title)}:</b>\n"
                f"#UNMUTE\n"
                f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
                f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}"
            )
    else:
        await message.reply_text(
            "This user isn't even in the chat, unmuting them won't make them talk"
            " more than they already do!",
        )

    return ""


@on_message(filters.command(["tmute", "tempmute", "dtmute"]), chained=True)
@connection_status
@loggable
@check_admin(permission="can_restrict_members", is_both=True)
async def temp_mute(client, message: Message) -> str:
    chat = message.chat
    user = message.from_user

    try:
        await _delete_replied(message)
    except _StopCommand:
        return ""

    args = message.command[1:] if len(message.command) > 1 else []
    user_id, reason = await extract_user_and_text(message, args)
    reply = await check_user(user_id, client, chat)

    if reply:
        await message.reply_text(reply)
        return ""

    member = await client.get_chat_member(chat.id, user_id)

    if not reason:
        await message.reply_text("You haven't specified a time to mute this user for!")
        return ""

    split_reason = reason.split(None, 1)

    time_val = split_reason[0].lower()
    if len(split_reason) > 1:
        reason = split_reason[1]
    else:
        reason = ""

    mutetime = await extract_time(message, time_val)

    if not mutetime:
        return ""

    log = (
        f"<b>{html.escape(chat.title)}:</b>\n"
        f"#TEMP MUTED\n"
        f"<b>Admin:</b> {mention_html(user.id, user.first_name)}\n"
        f"<b>User:</b> {mention_html(member.user.id, member.user.first_name)}\n"
        f"<b>Time:</b> {time_val}"
    )
    if reason:
        log += f"\n<b>Reason:</b> {html.escape(reason)}"

    try:
        if member.status in RESTRICTED_OR_MEMBER:
            chat_permissions = ChatPermissions(can_send_messages=False)
            until_dt = datetime.fromtimestamp(mutetime, timezone.utc)
            await client.restrict_chat_member(
                chat.id,
                user_id,
                chat_permissions,
                until_date=until_dt,
            )
            await client.send_message(
                chat.id,
                f"Muted <b>{html.escape(member.user.first_name)}</b> for {time_val}!",
                parse_mode=ParseMode.HTML,
                message_thread_id=message.message_thread_id if chat.is_forum else None,
            )
            return log
        else:
            await message.reply_text("This user is already muted.")

    except RPCError as excp:
        if "reply message not found" in str(excp.message or excp).lower():
            # Do not reply
            await message.reply_text(f"Muted for {time_val}!")
            return log
        else:
            LOGGER.exception(
                "ERROR muting user %s in chat %s (%s) due to %s",
                user_id,
                chat.title,
                chat.id,
                excp,
            )
            await message.reply_text("Well damn, I can't mute that user.")

    return ""


__help__ = """
➠ *Admins only:*

» /mute <userhandle>: silences a user. Can also be used as a reply, muting the replied to user.

» /tmute <userhandle> x(m/h/d): mutes a user for x time. (via handle, or reply). `m` = `minutes`, `h` = `hours`, `d` = `days`.
» /dmute <userhandle>: Delete the replied message and mute the user. Must be a reply.
» /dtmute <userhandle> x(m/h/d): Same as above, but mutes temporarily.

» /unmute <userhandle>: unmutes a user. Can also be used as a reply, muting the replied to user.
"""

__mod_name__ = "MUTE"
