from pyrogram.errors import RPCError

from Mikobot.utils.gate import requirement


async def send_message(message, text, *args, **kwargs):
    """reply_text(), retried once when Telegram errors."""
    try:
        return await message.reply_text(text, *args, **kwargs)
    except RPCError:
        return await message.reply_text(text, *args, **kwargs)


def typing_action(func):
    """Sends typing action while processing func command."""
    return requirement(chat_action="typing")(func)
