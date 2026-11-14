# <============================================== IMPORTS =========================================================>
from datetime import datetime, timezone
from functools import wraps

from pyrogram import filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import LinkPreviewOptions, Message

from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    import html

    from Database.sql import log_channel_sql as sql
    from Mikobot import EVENT_LOGS, LOGGER
    from Mikobot import app as client
    from Mikobot.plugins.helper_funcs.chat_status import check_admin
    from Mikobot.utils.parser import escape_markdown

    # <=======================================================================================================>
    # <================================================ FUNCTION =======================================================>
    def _event_message(args, kwargs):
        """Find the Message in a handler's arguments."""
        message = kwargs.get("message")
        if message is None:
            message = next((a for a in args if isinstance(a, Message)), None)
        return message

    def loggable(func):
        """Post the handler's return value to the chat's log channel."""

        @wraps(func)
        async def log_action(*args, **kwargs):
            message = _event_message(args, kwargs)
            result = await func(*args, **kwargs)
            if message is None:
                return result

            chat = message.chat

            if result and isinstance(result, str):
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result += f"\nEvent stamp: {datetime.now(timezone.utc).strftime(datetime_fmt)}"

                if chat.is_forum and chat.username:
                    result += f"\nLink: https://t.me/{chat.username}/{message.message_thread_id}/{message.id}"

                if chat.type == ChatType.SUPERGROUP and chat.username:
                    result += f"\nLink: https://t.me/{chat.username}/{message.id}"
                log_chat = sql.get_chat_log_channel(chat.id)
                if log_chat:
                    try:
                        await send_log(log_chat, chat.id, result)
                    except Exception:
                        LOGGER.exception(
                            "Unable to deliver per-chat log for chat %s to channel %s",
                            chat.id,
                            log_chat,
                        )

            return result

        return log_action

    def gloggable(func):
        """Post the handler's return value to the global event log channel."""

        @wraps(func)
        async def glog_action(*args, **kwargs):
            message = _event_message(args, kwargs)
            result = await func(*args, **kwargs)
            if message is None:
                return result
            chat = message.chat

            if result:
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result += f"\nEvent stamp: {datetime.now(timezone.utc).strftime(datetime_fmt)}"
                if chat.is_forum and chat.username:
                    result += f"\nLink: https://t.me/{chat.username}/{message.message_thread_id}/{message.id}"
                elif chat.type == ChatType.SUPERGROUP and chat.username:
                    result += f"\nLink: https://t.me/{chat.username}/{message.id}"
                if EVENT_LOGS:
                    try:
                        await send_log(EVENT_LOGS, chat.id, result)
                    except Exception:
                        LOGGER.exception(
                            "Unable to deliver global log for chat %s to channel %s",
                            chat.id,
                            EVENT_LOGS,
                        )

            return result

        return glog_action

    async def send_log(log_chat_id: str, orig_chat_id: str, result: str):
        is_chat_log = log_chat_id == sql.get_chat_log_channel(orig_chat_id)
        try:
            await client.send_message(
                log_chat_id,
                result,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except RPCError as excp:
            if "chat not found" in str(excp.message or excp).lower():
                if not is_chat_log:
                    LOGGER.warning(
                        "Global log channel %s is unavailable; per-chat logging is unchanged",
                        log_chat_id,
                    )
                    return
                try:
                    await client.send_message(
                        orig_chat_id,
                        "This log channel has been deleted - unsetting.",
                        message_thread_id=1,
                    )
                except RPCError:
                    await client.send_message(
                        orig_chat_id,
                        "This log channel has been deleted - unsetting.",
                    )
                sql.stop_chat_logging(orig_chat_id)
            else:
                LOGGER.warning("Unable to parse audit log: %s", excp.message)
                LOGGER.exception(
                    "Audit log formatting failed for channel %s", log_chat_id
                )

                try:
                    await client.send_message(
                        log_chat_id,
                        result
                        + "\n\nFormatting has been disabled due to an unexpected error.",
                    )
                except RPCError:
                    LOGGER.warning(
                        "Unable to deliver unformatted audit log to channel %s",
                        log_chat_id,
                        exc_info=True,
                    )

    @on_message(filters.command("logchannel"), chained=True)
    @check_admin(is_user=True)
    async def logging(client, message: Message):
        log_channel = sql.get_chat_log_channel(message.chat.id)
        if log_channel:
            log_channel_info = await client.get_chat(log_channel)
            await message.reply_text(
                f"This group has all its logs sent to: {escape_markdown(log_channel_info.title)} (`{log_channel}`)",
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            await message.reply_text("No log channel has been set for this group!")

    @on_message(filters.command("setlog"), chained=True)
    @check_admin(is_user=True)
    async def setlog(client, message: Message):
        chat = message.chat
        f_chat = None
        if getattr(message, "forward_origin", None):
            f_chat = getattr(message.forward_origin, "chat", None) or getattr(
                message.forward_origin, "sender_chat", None
            )
        if f_chat is None:
            f_chat = getattr(message, "forward_from_chat", None)

        if chat.type == ChatType.CHANNEL:
            await client.send_message(
                chat.id,
                "Now, forward the /setlog to the group you want to tie this channel to!",
            )

        elif f_chat:
            sql.set_chat_log_channel(chat.id, f_chat.id)

            try:
                await client.send_message(
                    f_chat.id,
                    f"This channel has been set as the log channel for {html.escape(chat.title or chat.first_name)}.",
                )
            except RPCError:
                LOGGER.exception("Error in setting the log channel.")

            if chat.is_forum:
                await client.send_message(
                    chat.id,
                    "Successfully set log channel!",
                    message_thread_id=message.message_thread_id,
                )
            else:
                await client.send_message(chat.id, "Successfully set log channel!")

        else:
            await message.reply_text(
                "The steps to set a log channel are:\n"
                " - Add bot to the desired channel (as an admin!)\n"
                " - Send /setlog in the channel\n"
                " - Forward the /setlog to the group\n",
            )

    @on_message(filters.command("unsetlog"), chained=True)
    @check_admin(is_user=True)
    async def unsetlog(client, message: Message):
        chat = message.chat

        log_channel = sql.stop_chat_logging(chat.id)
        if log_channel:
            await client.send_message(
                log_channel,
                f"Channel has been unlinked from {html.escape(chat.title)}",
            )
            await message.reply_text("Log channel has been un-set.")

        else:
            await message.reply_text("No log channel is set yet!")

    def __stats__():
        return f"• {sql.num_logchannels()} log channels set."

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    async def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            log_channel_info = await client.get_chat(log_channel)
            return f"This group has all its logs sent to: {escape_markdown(log_channel_info.title)} (`{log_channel}`)"
        return "No log channel is set for this group!"

    # <=================================================== HELP ====================================================>

    __help__ = """
➠ *Admins Only*

» /logchannel: Get log channel info.

» /setlog: Set the log channel.

» /unsetlog: Unset the log channel.

➠ *Setting the log channel is done by:*
➠ *Adding the bot to the desired channel (as an admin!)*

» Sending /setlog in the channel
» Forwarding the /setlog to the group
"""

    __mod_name__ = "LOG-SET"

else:
    # run anyway if module not loaded
    def loggable(func):
        return func

    def gloggable(func):
        return func


# <================================================ END =======================================================>
