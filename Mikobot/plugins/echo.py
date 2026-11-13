"""Echo text back through the bot, and broadcast it to every known chat.

/echo and /say post the supplied text as the client. Anyone who can do that can
make the bot appear to say something it never said, so both are limited to the
bot's own owners and developers rather than group admins: in a group the bot
is an authority, and a borrowed voice is a convincing forgery.

Formatting is preserved by copying the replied-to message when there is one,
which keeps entities intact; plain text falls back to sending the string.

Broadcast mirrors /gcast's delivery loop and chat list; the two differ only in
which client sends. A FloodWait is honoured rather than counted as a failure,
because a fan-out past a few hundred chats hits the rate limit by design.
"""

import asyncio

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import Message

import Database.sql.users_sql as users_sql
from Mikobot import DEV_USERS, LOGGER, OWNER_ID
from Mikobot.events import on_message

# Flood protection: Telegram rejects bursts, and a broadcast to many chats
# is exactly that. Sending must never outrun the account's rate limit.
BROADCAST_DELAY = 0.3


def _is_bot_staff(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in DEV_USERS


async def _send_echo(client, message: Message) -> None:
    if not message.from_user or not _is_bot_staff(message.from_user.id):
        await message.reply_text("Only the bot owners can do that.")
        return

    replied = message.reply_to_message
    text = " ".join(message.command[1:])
    if not text and replied is None:
        await message.reply_text("Give me something to say, or reply to a message.")
        return

    try:
        if replied is not None:
            # Copying keeps the original entities, so markup and links survive.
            await replied.copy(message.chat.id)
        else:
            await message.reply_text(text, parse_mode=ParseMode.HTML)
    except RPCError as exc:
        LOGGER.warning("Echo failed in %s: %s", message.chat.id, exc)
        await message.reply_text("I could not send that here.")

    try:
        await message.delete()
    except RPCError:
        # Not fatal: the command is gone from view either way, and an admin
        # may have deletes disabled.
        pass


async def _broadcast(client, message: Message) -> None:
    if not message.from_user or not _is_bot_staff(message.from_user.id):
        await message.reply_text("Only the bot owners can do that.")
        return

    replied = message.reply_to_message
    text = " ".join(message.command[1:])
    if not text and replied is None:
        await message.reply_text("Give me something to broadcast, or reply to one.")
        return

    chats = await asyncio.to_thread(users_sql.get_all_chats) or []
    if not chats:
        await message.reply_text("I am not in any chats yet.")
        return

    status = await message.reply_text(
        f"Broadcasting to <code>{len(chats)}</code> chats...", parse_mode=ParseMode.HTML
    )

    sent = failed = deferred = 0
    for chat in chats:
        for attempt in (1, 2):
            try:
                if replied is not None:
                    await replied.copy(chat.chat_id)
                else:
                    await client.send_message(
                        chat.chat_id, text, parse_mode=ParseMode.HTML
                    )
                sent += 1
                break
            except FloodWait as exc:
                # The API named the wait; waiting is what this request needs.
                if attempt == 2:
                    deferred += 1
                    break
                await asyncio.sleep(exc.retry_after)
            except RPCError:
                # A chat the bot was removed from, or one with posting disabled.
                failed += 1
                break
            except Exception:
                LOGGER.exception("Broadcast to %s failed", chat.chat_id)
                failed += 1
                break
        await asyncio.sleep(BROADCAST_DELAY)

    await status.edit_text(
        f"Broadcast finished.\nSent: <code>{sent}</code>\nFailed: <code>{failed}</code>"
        + (f"\nDeferred: <code>{deferred}</code>" if deferred else ""),
        parse_mode=ParseMode.HTML,
    )


__mod_name__ = "ECHO"

__help__ = """
➡ Post a message through the bot, or send one to every chat it knows.

➡ Bot owners only. These speak with the bot's authority, so leaving them
open to group admins would let anyone put words in the bot's mouth.

» /echo <text>: Send text as the client. Reply to a message to copy it with
its formatting intact.
» /say <text>: The same as /echo.
» /broadcast <text>: Send to every chat the bot is in. Reply to copy
formatting instead.
"""


@on_message(filters.command(["echo", "say"]), chained=True)
async def echo(client, message: Message):
    await _send_echo(client, message)


@on_message(filters.command("broadcast"), chained=True)
async def broadcast(client, message: Message):
    await _broadcast(client, message)
