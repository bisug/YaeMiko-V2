from asyncio import sleep
from itertools import batched

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.errors import MessageDeleteForbidden, RPCError
from pyrogram.types import Message

from Mikobot import SUPPORT_CHAT, app
from Mikobot.utils.can_restrict import can_restrict


@app.on_message(filters.command("purge"))
@can_restrict
async def purge(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    if m.reply_to_message:
        message_ids = list(range(m.reply_to_message.id, m.id))

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
        except RPCError as ef:
            await m.reply_text(
                text=f"""An error occurred. Report it to @{SUPPORT_CHAT}

      <b>Error:</b> <code>{ef}</code>"""
            )

        count_del_msg = len(message_ids)

        z = await m.reply_text(text=f"Deleted <i>{count_del_msg}</i> messages.")
        await sleep(3)
        await z.delete()
        return
    await m.reply_text("Reply to a message to start a purge.")
    return


@app.on_message(filters.command("spurge"))
@can_restrict
async def spurge(c: app, m: Message):
    if m.chat.type != ChatType.SUPERGROUP:
        await m.reply_text(text="Cannot purge messages in a basic group.")
        return

    if m.reply_to_message:
        message_ids = list(range(m.reply_to_message.id, m.id))

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
        except RPCError as ef:
            await m.reply_text(
                text=f"""An error occurred. Report it to @{SUPPORT_CHAT}

      <b>Error:</b> <code>{ef}</code>"""
            )
        return
    await m.reply_text("Reply to a message to start a silent purge.")
    return


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

/spurge: Delete messages up to the replied message without a success message.

/del: Delete a single message. Use as a reply to that message."""

__mod_name__ = "Purge"
