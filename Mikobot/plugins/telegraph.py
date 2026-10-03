# <============================================== IMPORTS =========================================================>
import asyncio
import os
import tempfile
import time
from pathlib import Path

from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message
from telegraph import Telegraph, exceptions

from Mikobot import app
from Mikobot.utils.errors import capture_err

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.command(["tgm", "tmg", "telegraph"], prefixes="/"))
@capture_err
async def telegraph_upload(client: Client, message: Message):
    replied = message.reply_to_message
    if not replied or not replied.media:
        await message.reply("Reply to a photo, video, animation, or document.")
        return

    status = await message.reply("Downloading and uploading to Telegraph…")
    media = replied.media
    if getattr(media, "file_size", 0) > 20 * 1024 * 1024:
        await status.edit_text("That media is too large to upload (20 MB maximum).")
        return
    with tempfile.TemporaryDirectory(prefix="yae-telegraph-") as temp_dir:
        # file_name has to name the file, not the directory holding it.
        # os.path.split() turns the bare directory into (parent, "yae-telegraph-x"),
        # so kurigram downloads onto the temp dir's own path and shutil.move ends
        # up dropping the file inside it, leaving the directory as the return
        # value. The trailing separator is what makes split() yield the directory
        # itself and an empty name, which is also what keeps kurigram's own
        # naming, and therefore the .webp suffix check below, working.
        downloaded_file = await client.download_media(
            replied, file_name=temp_dir + os.sep
        )
        if not downloaded_file:
            await status.edit_text("The replied media could not be downloaded.")
            return

        upload_path = Path(downloaded_file)
        # kurigram hands back the directory rather than a file when the two
        # collide, so this is checked instead of assumed.
        if not upload_path.is_file():
            await status.edit_text("The replied media could not be downloaded.")
            return
        if upload_path.suffix.lower() == ".webp":
            png_path = upload_path.with_suffix(".png")
            with Image.open(upload_path) as image:
                image.save(png_path, "PNG")
            upload_path = png_path

        started = time.perf_counter()
        try:
            # The module level telegraph.upload_file warns and delegates here.
            # Both hit the same endpoint; only this one is not deprecated.
            uploaded = await asyncio.to_thread(Telegraph().upload_file, str(upload_path))
        except exceptions.TelegraphException:
            await status.edit_text("Telegraph rejected the upload. Please try again later.")
            return

    if not uploaded or not uploaded[0].get("src"):
        await status.edit_text("Telegraph did not return an upload URL.")
        return

    elapsed = time.perf_counter() - started
    path = uploaded[0]["src"]
    await status.edit_text(
        f"➼ **Uploaded to [Telegraph](https://telegra.ph{path}) "
        f"in {elapsed:.2f} seconds.**\n\n"
        f"➼ **Copy Link:** `https://telegra.ph{path}`"
    )

# <=================================================== HELP ====================================================>
__help__ = """ 
➠ *TELEGRAPH*:

» /tgm, /tmg, /telegraph*:* `get telegram link of replied media`
 """

__mod_name__ = "TELEGRAPH"
# <================================================ END =======================================================>
