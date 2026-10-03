# <============================================== IMPORTS =========================================================>
from aiogram.exceptions import TelegramAPIError

from Mikobot.utils.gate import requirement

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def send_message(message, text, *args, **kwargs):
    """answer(), retried once when the Telegram API errors.

    The original second attempt dropped PTB's do_quote kwarg, which aiogram
    does not have, so the retry became a verbatim repeat of the first call and
    did nothing for a rejected quote. It is kept as a single retry because a
    TelegramNetworkError is transient and the repeat is what recovers from it.
    """
    try:
        return await message.answer(text, *args, **kwargs)
    except TelegramAPIError:
        return await message.answer(text, *args, **kwargs)


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
