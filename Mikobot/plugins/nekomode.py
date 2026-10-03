# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX
# NEKOS

# <============================================== IMPORTS =========================================================>
import asyncio

from Database.sql.toggle_sql import is_nekomode_on, nekomode_off, nekomode_on
from pyrogram import filters

from Mikobot import app
from Mikobot.state import state  # Import the state function

# <=======================================================================================================>

# api.waifu.pics stopped resolving, which took all 31 of the commands below with
# it. nekos.life serves the same category names and is the backend the nekos.py
# dependency already talks to, so the surviving ten are fetched from there.
# Probed live: every name listed here returns a URL, and these are the ones
# among the old list that the service actually answers. The removed twenty
# return HTTP 500 and have no equivalent, so advertising them was the bug.
url_sfw = "https://nekos.life/api/v2/img/"

allowed_commands = [
    "waifu",
    "neko",
    "cuddle",
    "hug",
    "kiss",
    "pat",
    "smug",
    "spank",
    "slap",
    "tickle",
]


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.regex(r"^/wallpaper(?:@\S+)?$"), group=1)
async def wallpaper(_, event):
    chat_id = event.chat.id
    nekomode_status = is_nekomode_on(chat_id)
    if nekomode_status:
        import nekos

        target = "wallpaper"
        try:
            img_url = await asyncio.to_thread(nekos.img, target)
        except Exception:
            await event.reply("The neko service is unavailable. Please try again later.")
            return
        await event.reply(file=img_url)


@app.on_message(filters.regex(r"^/nekomode on(?:@\S+)?$"), group=1)
async def enable_nekomode(_, event):
    chat_id = event.chat.id
    nekomode_on(chat_id)
    await event.reply("Nekomode has been enabled.")


@app.on_message(filters.regex(r"^/nekomode off(?:@\S+)?$"), group=1)
async def disable_nekomode(_, event):
    chat_id = event.chat.id
    nekomode_off(chat_id)
    await event.reply("Nekomode has been disabled.")


@app.on_message(filters.regex(r"^/(?:{})(?:@\S+)?$".format("|".join(allowed_commands))), group=1)
async def nekomode_commands(_, event):
    chat_id = event.chat.id
    nekomode_status = is_nekomode_on(chat_id)
    if nekomode_status:
        target = event.text.split()[0].split("@", 1)[0][1:].lower()  # Remove the slash before the command
        if target in allowed_commands:
            url = f"{url_sfw}{target}"

            try:
                response = await state.get(url, timeout=10)
                response.raise_for_status()
                media_url = response.json().get("url")
                if not isinstance(media_url, str) or not media_url.startswith("http"):
                    raise ValueError("The neko service returned an invalid response.")
            except Exception:
                await event.reply("The neko service is unavailable. Please try again later.")
                return

            # Most categories answer with a gif, but spank and neko return a
            # still image often enough that sending everything as an animation
            # fails on the upload.
            if media_url.lower().endswith((".gif", ".mp4")):
                await event.reply_animation(media_url)
            else:
                await event.reply_photo(media_url)


__help__ = """
*✨ Sends fun Gifs/Images*

➥ /nekomode on : Enables fun neko mode.
➥ /nekomode off : Disables fun neko mode

» /waifu: sends a random waifu.
» /neko: sends a random neko.
» /wallpaper: sends random wallpapers.
» /tickle: sends random tickle GIFs.
» /kiss: sends random kissing GIFs.
» /cuddle: sends random cuddle GIFs.
» /smug: sends random smug GIFs.
» /slap: sends random slap GIFs.
» /hug: sends a random hug GIF.
» /pat: sends a random pat GIF.
» /spank: sends a random spank.
"""

__mod_name__ = "NEKO"
# <================================================ END =======================================================>
