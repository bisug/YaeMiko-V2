import asyncio
from time import gmtime, strftime, time

from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from Mikobot import store, user_data
from Mikobot.events import on_callback, on_message
from Mikobot.logger import LOGGER
from Mikobot.plugins.helper_funcs.chat_status import check_admin

UPTIME = time()  # Baseline for the uptime readout in /pyroping


@on_message(filters.command("id"), chained=True)
async def _id(client, message: Message):
    chat = message.chat
    your_id = message.from_user.id
    mention_user = message.from_user.mention
    message_id = message.id
    reply = message.reply_to_message

    text = f"Message ID: [{message_id}]({message.link})\n"
    text += f"User: [{mention_user}](tg://user?id={your_id}) `{your_id}`\n"

    if not message.command:
        message.command = message.text.split()

    if not message.command:
        message.command = message.text.split()

    if len(message.command) == 2:
        try:
            split = message.text.split(None, 1)[1].strip()
            user_id = (await client.get_users(split)).id
            user_mention = (await client.get_users(split)).mention
            text += f"User: [{user_mention}](tg://user?id={user_id}) `{user_id}`\n"

        except Exception:
            return await message.reply_text("That user does not exist.")

    text += f"Chat ID: [{chat.id}](https://t.me/{chat.username})\n\n"

    forward_chat = None
    if getattr(message, "forward_origin", None):
        forward_chat = getattr(message.forward_origin, "chat", None) or getattr(
            message.forward_origin, "sender_chat", None
        )

    if not getattr(reply, "empty", True) and not forward_chat and not reply.sender_chat:
        text += f"Replied message ID: [{message.reply_to_message.id}]({reply.link})\n"
        text += f"Replied user ID: [{reply.from_user.id}](tg://user?id={reply.from_user.id})\n\n"

    reply_forward_chat = None
    if reply and getattr(reply, "forward_origin", None):
        reply_forward_chat = getattr(reply.forward_origin, "chat", None) or getattr(
            reply.forward_origin, "sender_chat", None
        )

    if reply_forward_chat:
        text += f"Forwarded channel {reply_forward_chat.title} has ID `{reply_forward_chat.id}`\n\n"

    if reply and reply.sender_chat:
        text += f"ID of the replied chat or channel: `{reply.sender_chat.id}`"

    sticker_id = (
        "CAACAgIAAx0EdppwYAABAgotZg5rBL4P05Xjmy80p7DdNdneDmUAAnccAALIWZhJPyYLf3FzPHs0BA"
    )
    await message.reply_sticker(sticker=sticker_id)
    await message.reply_text(
        text, link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


@on_message(filters.command("logs"), chained=True)
@check_admin(only_dev=True)
async def logs(client, message: Message):
    with open("Logs.txt", "rb") as f:
        caption = "Log file:"
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Close", callback_data="close", style=ButtonStyle.PRIMARY
                    )
                ]
            ]
        )
        sent = await client.send_document(
            document=f,
            file_name=f.name,
            caption=caption,
            reply_markup=reply_markup,
            chat_id=message.from_user.id,
        )

        user_data.setdefault(message.from_user.id, {})["log_message_id"] = sent.id
        await asyncio.to_thread(store.save)


@on_callback(filters.regex(r"^close$"), chained=True)
@check_admin(only_dev=True)
async def close_callback(client, query: CallbackQuery):
    message_id = user_data.get(query.from_user.id, {}).get("log_message_id")
    if message_id:
        try:
            await client.delete_messages(
                chat_id=query.message.chat.id, message_ids=message_id
            )
            user_data[query.from_user.id].pop("log_message_id", None)
            await asyncio.to_thread(store.save)
            await query.answer()
        except Exception:
            await query.answer("Unable to close this log.", show_alert=True)
    else:
        await query.answer("This log has already been closed.")


@on_message(filters.command("pyroping"), chained=True)
async def ping(client, m: Message):
    LOGGER.info(f"{m.from_user.id} used ping cmd in {m.chat.id}")
    start = time()
    replymsg = await m.reply_text(text="Pinging...")
    delta_ping = time() - start

    up = strftime("%Hh %Mm %Ss", gmtime(time() - UPTIME))
    image_url = "https://telegra.ph/file/e1049f371bbec3f006f3a.jpg"

    await replymsg.reply_photo(
        photo=image_url,
        caption=f"<b>Pyro-Pong!</b>\n{delta_ping * 1000:.3f} ms\n\nUptime: <code>{up}</code>",
    )
    await replymsg.delete()


__help__ = """
Commands:
/instadl <link>: Get Instagram content such as reels or images.
/insta <link>: Same as /instadl.
/pyroping: Check the bot's ping.
/hyperlink <text> <link>: Create a Markdown hyperlink from the given text and link.
/pickwinner <participant1> <participant2> ...: Pick a random winner from the list.
"""

__mod_name__ = "Extra"
__command_list__ = ["id", "pyroping"]
