# <============================================== IMPORTS =========================================================>
from functools import wraps

from pyrogram.errors import FloodSkipFailedWait, FloodWait
from pyrogram.errors.exceptions.forbidden_403 import ChatWriteForbidden

from Mikobot import LOGGER

# <=======================================================================================================>


# <================================================ CONSTANTS =====================================================>
# Every 420 Telegram raises is a Flood, but not every Flood names a wait:
# FloodWait and FloodPremiumWait carry the seconds, while
# FloodSkipFailedWait (new in kurigram 2.2.27) says only that a short wait is
# required. Callers that sleep on the error therefore need one place that
# knows which of the two shapes arrived.
FLOOD_WAIT_ERRORS = (FloodWait, FloodSkipFailedWait)

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def flood_wait_seconds(error, default: int = 5) -> int:
    """How long to sleep for a 420 error, in seconds.

    kurigram exposes the wait as ``value`` (and ``seconds`` on FloodWait), but
    FloodSkipFailedWait carries no number at all: its message is "A short wait
    is required before repeating the request." Only FloodWait-style errors
    name a duration, so the rest fall back to ``default``.

    kurigram 2.2.27 also dropped the old ``error.x`` attribute these handlers
    used to read. Reading it raised AttributeError inside the ``except``
    block, which replaced the rate-limit handling with a crash.
    """
    value = getattr(error, "value", None)
    if isinstance(value, int) and value > 0:
        return value
    return default


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
