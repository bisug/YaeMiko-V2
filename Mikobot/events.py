# <============================================== IMPORTS =========================================================>
from pyrogram import filters
from pyrogram.handlers import (
    CallbackQueryHandler,
    ChatMemberUpdatedHandler,
    InlineQueryHandler,
    MessageHandler,
)

from Mikobot import app
def _with_client(callback):
    async def handler(client, event):
        return await callback(event)

    return handler





# <============================================== FUNCTIONS =========================================================>
def register(**args):
    """Registers a Kurigram message handler."""
    pattern = args.get("pattern")
    group = args.get("group", 0)

    def decorator(func):
        handler_filter = filters.regex(pattern) if pattern else filters.all
        app.add_handler(
            MessageHandler(_with_client(func), handler_filter),
            group=group,
        )
        return func

    return decorator


def chataction(**args):
    def decorator(func):
        app.add_handler(ChatMemberUpdatedHandler(_with_client(func)))
        return func

    return decorator


def userupdate(**args):
    def decorator(func):
        app.add_handler(ChatMemberUpdatedHandler(_with_client(func)))
        return func

    return decorator


def inlinequery(**args):
    pattern = args.get("pattern")

    def decorator(func):
        handler_filter = filters.regex(pattern) if pattern else filters.all
        app.add_handler(InlineQueryHandler(_with_client(func), handler_filter))
        return func

    return decorator


def callbackquery(**args):
    pattern = args.get("pattern")

    def decorator(func):
        handler_filter = filters.regex(pattern) if pattern else filters.all
        app.add_handler(CallbackQueryHandler(_with_client(func), handler_filter))
        return func

    return decorator


# <==================================================== END ===================================================>
