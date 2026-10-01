# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>
import random
import re

from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, Message

from Mikobot import dp

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
# Define the command handler for the "/pickwinner" command
async def pick_winner(message: Message, command: CommandObject):
    participants = command.args.split() if command.args else []

    if participants:
        # Select a random winner
        winner = random.choice(participants)

        # Send the winner as a reply
        await message.answer(f"🎉 The winner is: {winner}")
    else:
        # If no participants are provided
        await message.answer("Please provide a list of participants.")


# Define the command handler for the "/hyperlink" command
async def hyperlink_command(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) >= 2:
        text = " ".join(args[:-1])
        link = args[-1]
        hyperlink = f"[{text}]({link})"
        await message.answer(
            text=hyperlink, parse_mode=ParseMode.MARKDOWN, link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    else:
        match = re.search(r"/hyperlink ([^\s]+) (.+)", message.text)
        if match:
            text = match.group(1)
            link = match.group(2)
            hyperlink = f"[{text}]({link})"
            await message.answer(
                text=hyperlink, parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        else:
            await message.answer(
                "❌ Invalid format! Please use the format: /hyperlink <text> <link>."
            )


# <================================================ HANDLER =======================================================>
dp.message.register(pick_winner, Command("pickwinner"))
dp.message.register(hyperlink_command, Command("hyperlink"))
# <================================================ END =======================================================>
