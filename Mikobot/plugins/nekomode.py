# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX
# NEKOS

# <============================================== IMPORTS =========================================================>
import asyncio

from Database.mongodb.toggle_mongo import is_nekomode_on, nekomode_off, nekomode_on
from pyrogram import filters

from Mikobot import app
from Mikobot.state import state  # Import the state function

# <=======================================================================================================>

url_sfw = "https://api.waifu.pics/sfw/"

allowed_commands = [
    "waifu",
    "neko",
    "shinobu",
    "megumin",
    "bully",
    "cuddle",
    "cry",
    "hug",
    "awoo",
    "kiss",
    "lick",
    "pat",
    "smug",
    "bonk",
    "yeet",
    "blush",
    "smile",
    "spank",
    "wave",
    "highfive",
    "handhold",
    "nom",
    "bite",
    "glomp",
    "slap",
    "hTojiy",
    "wink",
    "poke",
    "dance",
    "cringe",
    "tickle",
]


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.regex(r"^/wallpaper(?:@\S+)?$"), group=1)
async def wallpaper(_, event):
    chat_id = event.chat.id
    nekomode_status = await is_nekomode_on(chat_id)
    if nekomode_status:
        import nekos

        target = "wallpaper"
        img_url = await asyncio.to_thread(nekos.img, target)
        await event.reply(file=img_url)


@app.on_message(filters.regex(r"^/nekomode on(?:@\S+)?$"), group=1)
async def enable_nekomode(_, event):
    chat_id = event.chat.id
    await nekomode_on(chat_id)
    await event.reply("Nekomode has been enabled.")


@app.on_message(filters.regex(r"^/nekomode off(?:@\S+)?$"), group=1)
async def disable_nekomode(_, event):
    chat_id = event.chat.id
    await nekomode_off(chat_id)
    await event.reply("Nekomode has been disabled.")


@app.on_message(filters.regex(r"^/(?:{})(?:@\S+)?$".format("|".join(allowed_commands))), group=1)
async def nekomode_commands(_, event):
    chat_id = event.chat.id
    nekomode_status = await is_nekomode_on(chat_id)
    if nekomode_status:
        target = event.text.split()[0].split("@", 1)[0][1:].lower()  # Remove the slash before the command
        if target in allowed_commands:
            url = f"{url_sfw}{target}"

            response = await state.get(url)
            result = response.json()
            animation_url = result["url"]

            # Send animation
            await event.reply_animation(animation_url)


__help__ = """
*✨ Sends fun Gifs/Images*

➥ /nekomode on : Enables fun neko mode.
➥ /nekomode off : Disables fun neko mode

» /bully: sends random bully gifs.
» /neko: sends random neko gifs.
» /wallpaper: sends random wallpapers.
» /highfive: sends random highfive gifs.
» /tickle: sends random tickle GIFs.
» /wave: sends random wave GIFs.
» /smile: sends random smile GIFs.
» /feed: sends random feeding GIFs.
» /blush: sends random blush GIFs.
» /avatar: sends random avatar stickers.
» /waifu: sends random waifu stickers.
» /kiss: sends random kissing GIFs.
» /cuddle: sends random cuddle GIFs.
» /cry: sends random cry GIFs.
» /bonk: sends random cuddle GIFs.
» /smug: sends random smug GIFs.
» /slap: sends random slap GIFs.
» /hug: get hugged or hug a user.
» /pat: pats a user or get patted.
» /spank: sends a random spank gif.
» /dance: sends a random dance gif.
» /poke: sends a random poke gif.
» /wink: sends a random wink gif.
» /bite: sends random bite GIFs.
» /handhold: sends random handhold GIFs.
"""

__mod_name__ = "NEKO"
# <================================================ END =======================================================>
