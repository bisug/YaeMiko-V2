# <============================================== IMPORTS =========================================================>
import importlib
import re

from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

import Database.sql.toggle_sql as toggle_sql
from Mikobot import dp
from Mikobot.plugins.helper_funcs.chat_status import ADMIN_CACHE, check_admin, connection_status
from Mikobot.plugins.helper_funcs.misc import is_module_loaded
from Mikobot.utils.cmdprefix import CMD_STARTERS
from Mikobot.utils.parser import escape_markdown

# <=======================================================================================================>

FILENAME = __name__.rsplit(".", 1)[-1]

DISABLE_CMDS = []
DISABLE_OTHER = []
ADMIN_CMDS = []

# <=======================================================================================================>

if is_module_loaded(FILENAME):
    from Database.sql import disable_sql as sql

    # <================================================ CLASS =======================================================>
    class NotDisabled(BaseFilter):
        """Swallow a command the chat turned off. Admins still get through.

        Replaces DisableAbleCommandHandler. aiogram has no handler classes to
        subclass, so this runs after Command(...) has injected the parsed
        command and answers with False to stop propagation.
        """

        def __init__(self, admin_ok: bool = False):
            self.admin_ok = admin_ok

        async def __call__(
            self, message: Message, command: CommandObject | None = None
        ) -> bool:
            if command is None:
                return True
            name = command.command.lower()
            if not sql.is_command_disabled(message.chat.id, name):
                return True
            if self.admin_ok and message.from_user:
                if message.from_user.id in ADMIN_CACHE.get(message.chat.id, ()):
                    return True
            return False

    class NotDisabledFriendly(BaseFilter):
        """Replaces DisableAbleMessageHandler for non-command handlers."""

        def __init__(self, friendly: str):
            self.friendly = friendly

        async def __call__(self, message: Message) -> bool:
            return not sql.is_command_disabled(message.chat.id, self.friendly)

    def disableable(
        commands: str | list, admin_ok: bool = False
    ) -> tuple:
        """Return the filters for a toggleable command, in the order they must run."""
        names = [commands] if isinstance(commands, str) else list(commands)
        for name in names:
            if not re.match(r"^[\da-z_]{1,32}$", name):
                raise ValueError(f"Command `{name}` is not a valid bot command")

        DISABLE_CMDS.extend(names)
        if admin_ok:
            ADMIN_CMDS.extend(names)

        # aiogram takes one prefix string and treats each char as a
        # separate command prefix, so CMD_STARTERS packs into it.
        return Command(
            commands=names, prefix="".join(CMD_STARTERS)
        ), NotDisabled(admin_ok)

    def disableable_friendly(friendly: str) -> NotDisabledFriendly:
        DISABLE_OTHER.append(friendly)
        return NotDisabledFriendly(friendly)

    # <=======================================================================================================>

    # <================================================ FUNCTION =======================================================>
    @connection_status
    @check_admin(is_user=True)
    async def disable(message: Message, command: CommandObject):
        args = command.args.split() if command.args else []
        if len(args) >= 1:
            disable_cmd = args[0]
            if disable_cmd.startswith(CMD_STARTERS):
                disable_cmd = disable_cmd[1:]

            if disable_cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                sql.disable_command(message.chat.id, str(disable_cmd).lower())
                await message.answer(
                    f"Disabled the use of `{disable_cmd}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await message.answer("That command can't be disabled")

        else:
            await message.answer("What should I disable?")

    @connection_status
    @check_admin(is_user=True)
    async def disable_module(message: Message, command: CommandObject) -> None:
        args = command.args.split() if command.args else []
        if len(args) >= 1:
            module_path = "Mikobot.plugins." + args[0].rsplit(".", 1)[0]

            try:
                module = importlib.import_module(module_path)
            except Exception:
                await message.answer("Does that module even exsist?")
                return

            try:
                command_list = module.__command_list__
            except Exception:
                await message.answer("Module does not contain command list!")
                return

            disabled_cmds = []
            failed_disabled_cmds = []

            for disable_cmd in command_list:
                if disable_cmd.startswith(CMD_STARTERS):
                    disable_cmd = disable_cmd[1:]

                if disable_cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                    sql.disable_command(message.chat.id, str(disable_cmd).lower())
                    disabled_cmds.append(disable_cmd)
                else:
                    failed_disabled_cmds.append(disable_cmd)

            if disabled_cmds:
                disabled_cmds_string = ", ".join(disabled_cmds)
                await message.answer(
                    f"Disabled the use of`{disabled_cmds_string}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

            if failed_disabled_cmds:
                failed_disabled_cmds_string = ", ".join(failed_disabled_cmds)
                await message.answer(
                    f"Commands `{failed_disabled_cmds_string}` can't be disabled",
                    parse_mode=ParseMode.MARKDOWN,
                )

        else:
            await message.answer("What should I disable?")

    @connection_status
    @check_admin(is_user=True)
    async def enable(message: Message, command: CommandObject):
        args = command.args.split() if command.args else []
        if len(args) >= 1:
            enable_cmd = args[0]
            if enable_cmd.startswith(CMD_STARTERS):
                enable_cmd = enable_cmd[1:]

            if sql.enable_command(message.chat.id, enable_cmd):
                await message.answer(
                    f"Enabled the use of`{enable_cmd}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await message.answer("Is that even disabled?")

        else:
            await message.answer("What sould I enable?")

    @connection_status
    @check_admin(is_user=True)
    async def enable_module(message: Message, command: CommandObject):
        args = command.args.split() if command.args else []

        if len(args) >= 1:
            module_path = "Mikobot.plugins." + args[0].rsplit(".", 1)[0]

            try:
                module = importlib.import_module(module_path)
            except Exception:
                await message.answer("Does that module even exsist?")
                return

            try:
                command_list = module.__command_list__
            except Exception:
                await message.answer("Module does not contain command list!")
                return

            enabled_cmds = []
            failed_enabled_cmds = []

            for enable_cmd in command_list:
                if enable_cmd.startswith(CMD_STARTERS):
                    enable_cmd = enable_cmd[1:]

                if sql.enable_command(message.chat.id, enable_cmd):
                    enabled_cmds.append(enable_cmd)
                else:
                    failed_enabled_cmds.append(enable_cmd)

            if enabled_cmds:
                enabled_cmds_string = ", ".join(enabled_cmds)
                await message.answer(
                    f"Enabled the use of`{enabled_cmds_string}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

            if failed_enabled_cmds:
                failed_enabled_cmds_string = ", ".join(failed_enabled_cmds)
                await message.answer(
                    f"Are the commands `{failed_enabled_cmds_string}` even disabled?",
                    parse_mode=ParseMode.MARKDOWN,
                )

        else:
            await message.answer("What sould I enable?")

    @connection_status
    @check_admin(is_user=True)
    async def list_cmds(message: Message):
        if DISABLE_CMDS + DISABLE_OTHER:
            result = ""
            for cmd in set(DISABLE_CMDS + DISABLE_OTHER):
                result += f" - `{escape_markdown(cmd)}`\n"
            await message.answer(
                f"The following commands are toggleable:\n{result}",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.answer("No commands can be disabled.")

    def build_curr_disabled(chat_id: str | int) -> str:
        disabled = sql.get_all_disabled(chat_id)
        if not disabled:
            return "No commands are disabled!"

        result = ""
        for cmd in disabled:
            result += " - `{}`\n".format(escape_markdown(cmd))
        return "The following commands are currently restricted:\n{}".format(result)

    @connection_status
    async def commands(message: Message):
        await message.answer(
            build_curr_disabled(message.chat.id),
            parse_mode=ParseMode.MARKDOWN,
        )

    def __stats__():
        return f"• {sql.num_disabled()} disabled items, across {sql.num_chats()} chats."

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)
        # Feature toggles live in their own table next to the disabled commands.
        toggle_sql.migrate_chat(old_chat_id, new_chat_id)

    def __chat_settings__(chat_id, user_id):
        return build_curr_disabled(chat_id)

    # <=================================================== HANDLER ====================================================>

    dp.message.register(disable, *disableable("disable"))
    dp.message.register(disable_module, *disableable("disablemodule"))
    dp.message.register(enable, *disableable("enable"))
    dp.message.register(enable_module, *disableable("enablemodule"))
    dp.message.register(commands, *disableable(["cmds", "disabled"]))
    dp.message.register(list_cmds, *disableable("listcmds"))

    # <=================================================== HELP ====================================================>
    __help__ = """
    » /cmds: Check the current status of disabled commands

    ➠ *Admins only*:

    » /enable < cmd name >: Enable that command.

    » /disable < cmd name >: Disable that command.

    » /enablemodule < module name >: Enable all commands in that module.

    » /disablemodule < module name >: Disable all commands in that module.

    » /listcmds: List all possible toggleable commands.
    """

    __mod_name__ = "DISABLE"
# <================================================ END ======================================================>
