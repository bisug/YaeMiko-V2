# <============================================== IMPORTS =========================================================>
from pyrogram.errors import RPCError

from Mikobot.utils.gate import requirement

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def send_message(message, text, *args, **kwargs):
    """reply_text(), retried once when Telegram errors.

    The original second attempt dropped PTB's do_quote kwarg, which neither
    framework has, so the retry became a verbatim repeat of the first call and
    did nothing for a rejected quote. It is kept as a single retry because a
    network error is transient and the repeat is what recovers from it.
    """
    try:
        return await message.reply_text(text, *args, **kwargs)
    except RPCError:
        return await message.reply_text(text, *args, **kwargs)


def typing_action(func):
    """Sends typing action while processing func command."""
    return requirement(chat_action="typing")(func)


def sticker_action(func):
    """Sends the choose-sticker action while processing func command."""
    return requirement(chat_action="choose_sticker")(func)


def document_action(func):
    """Sends the upload-document action while processing func command."""
    return requirement(chat_action="upload_document")(func)


def photo_action(func):
    """Sends the upload-photo action while processing func command."""
    return requirement(chat_action="upload_photo")(func)


# <================================================ END =======================================================>
