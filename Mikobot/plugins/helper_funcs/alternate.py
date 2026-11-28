from Mikobot.utils.gate import requirement


async def send_message(message, text, *args, **kwargs):
    """reply_text(); the session already retries transient failures."""
    return await message.reply_text(text, *args, **kwargs)


def typing_action(func):
    """Sends typing action while processing func command."""
    return requirement(chat_action="typing")(func)
