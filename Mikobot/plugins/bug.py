from pyrogram import filters
from pyrogram.enums import ParseMode

from Mikobot import app

BUG_REPORT_CHAT_IDS = [-1001989832800, -1001823656633]


@app.on_message(filters.command("bug", prefixes="/"))
async def bug_command_handler(client, message):
    if message.reply_to_message:
        replied_message = message.reply_to_message

        content = replied_message.text or replied_message.caption

        media_type = (
            "**Media content included**"
            if replied_message.photo
            or replied_message.document
            or replied_message.video
            or replied_message.audio
            or replied_message.animation
            else "**No media content included**"
        )

        sender_repr = (
            f"@{message.from_user.username}"
            if message.from_user and message.from_user.username
            else message.from_user.first_name
            if message.from_user
            else getattr(message.sender_chat, "title", "Anonymous")
        )
        report_message = f"**Bug reported by {sender_repr}:**\n\n{content}\n\n{media_type}\n\n**Message Link:** {replied_message.link}"

        await client.send_message(
            BUG_REPORT_CHAT_IDS[0], report_message, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await client.send_message(
            message.chat.id,
            "Reply to a message with /bug to report it.",
            parse_mode=ParseMode.MARKDOWN,
        )
