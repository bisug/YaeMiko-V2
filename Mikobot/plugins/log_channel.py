import asyncio
from datetime import datetime, timezone
from functools import wraps

from pyrogram import filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import ChannelPrivate, ChatInvalid, RPCError
from pyrogram.types import LinkPreviewOptions, Message

from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    import html

    from Database.sql import log_channel_sql as sql
    from Mikobot import EVENT_LOGS
    from Mikobot import app as client
    from Mikobot.logger import LOGGER
    from Mikobot.plugins.helper_funcs.chat_status import check_admin
    from Mikobot.utils.parser import escape_markdown

    def _event_message(args, kwargs):
        """Find the Message in a handler's arguments."""
        message = kwargs.get("message")
        if message is None:
            message = next((a for a in args if isinstance(a, Message)), None)
        return message

    def _log_category(func) -> str:
        """Pick a log category from the handler name for category filtering."""
        name = getattr(func, "__name__", "").lower()
        if "report" in name:
            return "reports"
        if "warn" in name:
            return "admin"
        if any(word in name for word in ("join", "leave", "welcome", "goodbye")):
            return "user"
        if any(
            word in name
            for word in ("flood", "raid", "blocklist", "blacklist", "lock", "nsfw")
        ):
            return "automated"
        if any(
            word in name
            for word in ("ban", "mute", "kick", "promote", "demote", "pin", "approve")
        ):
            return "admin"
        if any(
            word in name
            for word in ("settings", "reason", "filter", "note", "fed", "log")
        ):
            return "settings"
        return "other"

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
                        categories = await asyncio.to_thread(
                            sql.get_log_categories, chat.id
                        )
                        if not categories.get(_log_category(func), True):
                            return result
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

    async def send_log(log_chat_id: str | int, orig_chat_id: str | int, result: str):
        if isinstance(log_chat_id, str) and log_chat_id.strip().lstrip("-").isdigit():
            try:
                log_chat_id = int(log_chat_id.strip())
            except ValueError:
                pass
        if isinstance(orig_chat_id, str) and orig_chat_id.strip().lstrip("-").isdigit():
            try:
                orig_chat_id = int(orig_chat_id.strip())
            except ValueError:
                pass
        is_chat_log = str(log_chat_id) == str(sql.get_chat_log_channel(orig_chat_id))
        try:
            await client.send_message(
                log_chat_id,
                result,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except RPCError as excp:
            if isinstance(excp, (ChatInvalid, ChannelPrivate)):
                if not is_chat_log:
                    LOGGER.warning(
                        "Global log channel %s is unavailable; per-chat logging is unchanged",
                        log_chat_id,
                    )
                    return
                try:
                    await client.send_message(
                        orig_chat_id,
                        "This log channel was deleted. Unsetting it.",
                        message_thread_id=1,
                    )
                except RPCError:
                    await client.send_message(
                        orig_chat_id,
                        "This log channel was deleted. Unsetting it.",
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
            await message.reply_text("No log channel is set for this group.")

    @on_message(filters.command("setlog"), chained=True)
    @check_admin(is_user=True)
    async def setlog(client, message: Message):
        chat = message.chat
        f_chat = None
        if getattr(message, "forward_origin", None):
            f_chat = getattr(message.forward_origin, "chat", None) or getattr(
                message.forward_origin, "sender_chat", None
            )

        if chat.type == ChatType.CHANNEL:
            await client.send_message(
                chat.id,
                "Forward the /setlog to the group you want to link this channel to.",
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
                    "Log channel set.",
                    message_thread_id=message.message_thread_id,
                )
            else:
                await client.send_message(chat.id, "Log channel set.")

        else:
            await message.reply_text(
                "To set a log channel:\n"
                " - Add the bot to the desired channel as an admin\n"
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
            await message.reply_text("Log channel unset.")

        else:
            await message.reply_text("No log channel is set yet.")

    def _format_categories(categories) -> str:
        return "\n".join(
            f"{name}: {'on' if enabled else 'off'}"
            for name, enabled in categories.items()
        )

    async def _set_log_categories(message, enabled: bool) -> None:
        args = [
            arg.lower()
            for arg in (
                message.command[1:]
                if message.command and len(message.command) > 1
                else []
            )
        ]
        chat_id = message.chat.id
        if not args:
            categories = await asyncio.to_thread(sql.get_log_categories, chat_id)
            action = "log" if enabled else "nolog"
            await message.reply_text(
                f"Usage: /{action} <types...>\n" + _format_categories(categories)
            )
            return
        unknown = [arg for arg in args if arg not in sql.LOG_CATEGORIES]
        if unknown:
            await message.reply_text(
                f"Unknown log types: {', '.join(unknown)}. "
                f"Valid types: {', '.join(sql.LOG_CATEGORIES)}."
            )
            return
        for category in dict.fromkeys(args):
            await asyncio.to_thread(sql.set_log_category, chat_id, category, enabled)
        categories = await asyncio.to_thread(sql.get_log_categories, chat_id)
        await message.reply_text(_format_categories(categories))

    @on_message(filters.command("logcategories"), chained=True)
    @check_admin(is_user=True)
    async def log_categories(client, message: Message):
        categories = await asyncio.to_thread(sql.get_log_categories, message.chat.id)
        await message.reply_text(_format_categories(categories))

    @on_message(filters.command("log"), chained=True)
    @check_admin(is_user=True)
    async def enable_logs(client, message: Message):
        await _set_log_categories(message, True)

    @on_message(filters.command("nolog"), chained=True)
    @check_admin(is_user=True)
    async def disable_logs(client, message: Message):
        await _set_log_categories(message, False)

    def __stats__():
        return f"• {sql.num_logchannels()} log channels set."

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    async def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            log_channel_info = await client.get_chat(log_channel)
            return f"This group has all its logs sent to: {escape_markdown(log_channel_info.title)} (`{log_channel}`)"
        return "No log channel is set for this group."

    __help__ = """
➠ *Admin only:*

» /logchannel: Get log channel info.

» /setlog: Set the log channel.

» /unsetlog: Unset the log channel.

» /logcategories: Show which log categories are on.
» /log <types...>: Turn log categories on.
» /nolog <types...>: Turn log categories off.

Types: settings, admin, user, automated, reports, other.

➠ *To set the log channel:*
➠ *Add the bot to the desired channel as an admin*

» Send /setlog in the channel
» Forward the /setlog to the group
"""

    __mod_name__ = "Log-Set"

else:
    # run anyway if module not loaded
    def loggable(func):
        return func

    def gloggable(func):
        return func
