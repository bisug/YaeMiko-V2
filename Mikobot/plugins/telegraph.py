# <============================================== IMPORTS =========================================================>
import asyncio
import tempfile
import time
from pathlib import Path

from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import Message
from telegraph import exceptions, upload_file

from Mikobot import app
from Mikobot.utils.errors import capture_err

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.command(["tgm", "tmg", "telegraph"], prefixes="/"))
@capture_err
async def telegraph_upload(client: Client, message: Message):
    replied = message.reply_to_message
    if not replied or not replied.media:
        await message.reply_text("Reply to a photo, video, animation, or document.")
        return

    status = await message.reply_text("Downloading and uploading to Telegraph…")
    with tempfile.TemporaryDirectory(prefix="yae-telegraph-") as temp_dir:
        downloaded_file = await client.download_media(replied, file_name=temp_dir)
        if not downloaded_file:
            await status.edit_text("The replied media could not be downloaded.")
            return

        upload_path = Path(downloaded_file)
        if upload_path.suffix.lower() == ".webp":
            png_path = upload_path.with_suffix(".png")
            with Image.open(upload_path) as image:
                image.save(png_path, "PNG")
            upload_path = png_path

        started = time.perf_counter()
        try:
            media_urls = await asyncio.to_thread(upload_file, str(upload_path))
        except exceptions.TelegraphException:
            await status.edit_text("Telegraph rejected the upload. Please try again later.")
            return

    if not media_urls or not media_urls[0]:
        await status.edit_text("Telegraph did not return an upload URL.")
        return

    elapsed = time.perf_counter() - started
    path = media_urls[0]
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
