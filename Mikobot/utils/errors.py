# <============================================== IMPORTS =========================================================>
from functools import wraps

from pyrogram.errors.exceptions.forbidden_403 import ChatWriteForbidden

from Mikobot import LOGGER

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def capture_err(func):
    """Log and re-raise whatever a handler raises.

    Handlers reach this two ways. app.on_message calls them as
    (client, message), while the decorators in Mikobot.events wrap them so
    only the event is passed. The signature here accepts both, because a
    two-argument one raised TypeError on every callback query and was never
    used on one before.
    """

    @wraps(func)
    async def capture(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ChatWriteForbidden:
            LOGGER.info(
                "Skipped handler because the bot cannot write in chat %s",
                _event_chat_id(args),
            )
        except Exception:
            LOGGER.exception(
                "Handler failed in chat %s for user %s",
                _event_chat_id(args),
                _event_user_id(args),
            )
            raise

    return capture


def _event(args):
    """The Message or CallbackQuery out of a handler's positional arguments."""
    return args[1] if len(args) > 1 else (args[0] if args else None)


def _event_chat_id(args):
    # A CallbackQuery has no .chat of its own; the message it is attached to
    # carries it. getattr keeps a bare CallbackQuery from turning a logged
    # failure into a second failure here.
    event = _event(args)
    chat = getattr(event, "chat", None)
    if chat is None:
        chat = getattr(getattr(event, "message", None), "chat", None)
    return getattr(chat, "id", None)


def _event_user_id(args):
    user = getattr(_event(args), "from_user", None)
    return getattr(user, "id", None)


# <================================================ END =======================================================>
