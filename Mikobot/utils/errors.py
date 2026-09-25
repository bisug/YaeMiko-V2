# <============================================== IMPORTS =========================================================>
from functools import wraps

from pyrogram.errors.exceptions.forbidden_403 import ChatWriteForbidden

from Mikobot import LOGGER

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def capture_err(func):
    @wraps(func)
    async def capture(client, message, *args, **kwargs):
        try:
            return await func(client, message, *args, **kwargs)
        except ChatWriteForbidden:
            LOGGER.info(
                "Skipped handler because the bot cannot write in chat %s",
                message.chat.id if message.chat else None,
            )
        except Exception:
            LOGGER.exception(
                "Handler failed in chat %s for user %s",
                message.chat.id if message.chat else None,
                message.from_user.id if message.from_user else None,
            )
            raise

    return capture


# <================================================ END =======================================================>
