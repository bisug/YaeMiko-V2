from asyncio import sleep
from itertools import batched

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.errors import (
    MessageDeleteForbidden,
    MessageIdsEmpty,
    MessageIdsMismatch,
    RPCError,
)
from pyrogram.types import Message

from Mikobot import SUPPORT_CHAT, app
from Mikobot.utils.can_restrict import can_restrict

# Supergroup ID -> message ID that started a pending /purgefrom ... /purgeto.
PURGE_RANGES = {}


def parse_purge_count(args):
    """Number of recent messages to purge, or None for an invalid count."""
    if not args or not args[0].isdigit():
        return None
    count = int(args[0])
    return count if count > 0 else None


async def _purge(c, m: Message, message_ids, silent=False):
    if not message_ids:
        await m.reply_text(text="There are no messages to delete.")
        return

    m_list = list(map(list, batched(message_ids, 100, strict=False)))
    try:
        for plist in m_list:
            await c.delete_messages(
                chat_id=m.chat.id,
                message_ids=plist,
                revoke=True,
            )
        await m.delete()
    except MessageDeleteForbidden:
        await m.reply_text(
            text="Could not delete all messages. The messages may be too old, I may lack delete rights, or this may not be a supergroup."
        )
        return
    except MessageIdsEmpty, MessageIdsMismatch:
        await m.reply_text(
            text="Nothing was deleted. Those messages are no longer available."
        )
        return
    except RPCError as ef:
        await m.reply_text(
            text=f"""An error occurred. Report it to @{SUPPORT_CHAT}

      <b>Error:</b> <code>{ef}</code>"""
        )
        return

    if not silent:
        z = await m.reply_text(text=f"Deleted <i>{len(message_ids)}</i> messages.")
        await sleep(3)
        await z.delete()


@app.on_message(filters.command("purge"))
@can_restrict
async def purge(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    if m.reply_to_message:
        await _purge(c, m, list(range(m.reply_to_message.id, m.id)))
        return

    count = parse_purge_count(m.command[1:] if m.command else [])
    if count is not None:
        try:
            history = await c.get_chat_history(m.chat.id, limit=count)
            ids = [msg.id async for msg in history]
        except RPCError:
            await m.reply_text(text="Could not read the recent messages.")
            return
        ids.append(m.id)
        await _purge(c, m, ids)
        return

    await m.reply_text("Reply to a message to start a purge.")


@app.on_message(filters.command("spurge"))
@can_restrict
async def spurge(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    if m.reply_to_message:
        await _purge(c, m, list(range(m.reply_to_message.id, m.id)), silent=True)
        return
    await m.reply_text("Reply to a message to start a silent purge.")


@app.on_message(filters.command("purgefrom"))
@can_restrict
async def purge_from(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    start = m.reply_to_message.id if m.reply_to_message else m.id
    PURGE_RANGES[m.chat.id] = start
    await m.reply_text("Start of the purge marked. Use /purgeto to finish it.")


@app.on_message(filters.command("purgeto"))
@can_restrict
async def purge_to(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    start = PURGE_RANGES.pop(m.chat.id, None)
    if start is None:
        await m.reply_text("Use /purgefrom first to mark the start.")
        return

    end = m.reply_to_message.id if m.reply_to_message else m.id
    if end < start:
        await m.reply_text("The end of the range is before its start.")
        return

    ids = list(range(start, end + 1))
    if m.id not in ids:
        ids.append(m.id)
    await _purge(c, m, ids)


@app.on_message(
    filters.command("del"),
    group=9,
)
@can_restrict
async def del_msg(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        return

    if m.reply_to_message:
        await m.delete()
        await c.delete_messages(
            chat_id=m.chat.id,
            message_ids=m.reply_to_message.id,
        )
    else:
        await m.reply_text(text="What do you want to delete?")
    return


__help__ = """
Purge

/purge: Delete messages up to the replied message.
/purge <N>: Delete the last N messages.

/purgefrom: Mark the first message of a range. Use as a reply to pick it.
/purgeto: Delete from the marked message up to this one.

/spurge: Delete messages up to the replied message without a success message.

/del: Delete a single message. Use as a reply to that message."""

__mod_name__ = "Purge"
