import re

from pyrogram import filters

from Mikobot import app
from Mikobot.plugins.ai import get_ai_response


@app.on_message(filters.text & filters.regex(r"^Miko\s+", re.IGNORECASE))
async def miko_chat(client, message):
    prompt = message.text.split(maxsplit=1)[1].strip()
    if not prompt:
        return
    status = await message.reply("💭 Thinking...")
    answer = await get_ai_response(prompt)
    await status.edit_text(answer[:4096])


__help__ = """
➦ *Miko <question>: Ask the configured AI provider.*
➦ Powered by Google Gemini.
"""

__mod_name__ = "CHATBOT"
