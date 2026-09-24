# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>
import random
import re

from telegram import Update, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

from Mikobot import function

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
# Define the command handler for the "/pickwinner" command
async def pick_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the list of participants
    participants = context.args

    if participants:
        # Select a random winner
        winner = random.choice(participants)

        # Send the winner as a reply
        await update.message.reply_text(f"🎉 The winner is: {winner}")
    else:
        # If no participants are provided
        await update.message.reply_text("Please provide a list of participants.")


# Define the command handler for the "/hyperlink" command
async def hyperlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) >= 2:
        text = " ".join(args[:-1])
        link = args[-1]
        hyperlink = f"[{text}]({link})"
        await update.message.reply_text(
            text=hyperlink, parse_mode="Markdown", link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
    else:
        match = re.search(r"/hyperlink ([^\s]+) (.+)", update.message.text)
        if match:
            text = match.group(1)
            link = match.group(2)
            hyperlink = f"[{text}]({link})"
            await update.message.reply_text(
                text=hyperlink, parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        else:
            await update.message.reply_text(
                "❌ Invalid format! Please use the format: /hyperlink <text> <link>."
            )


# <================================================ HANDLER =======================================================>
function(CommandHandler("pickwinner", pick_winner, block=False))
function(CommandHandler("hyperlink", hyperlink_command, block=False))
# <================================================ END =======================================================>
