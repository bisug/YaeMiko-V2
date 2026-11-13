# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# <============================================== IMPORTS =========================================================>
import random
from sys import version_info

import pyrogram
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, Message

from Infamous.karma import ALIVE_ANIMATION, ALIVE_BTN
from Mikobot import BOT_NAME
from Mikobot.events import on_message

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def _crypto_backend_name() -> str:
    """The MTProto crypto backend in use.

    Kurigram picks the first importable of kuricrypt and tgcrypto and
    falls back to pyaes, so the same order is probed here. The backend
    is named rather than versioned because kuricrypt exposes no version
    attribute.
    """
    from importlib.util import find_spec

    for module_name in ("kuricrypt", "tgcrypto"):
        try:
            if find_spec(module_name) is not None:
                return module_name
        except ImportError, ValueError:
            continue
    return "pyaes"


@on_message(filters.command("alive"))
async def alive(client, message: Message):
    library_versions = {
        "KURIGRAM": pyrogram.__version__,
        "CRYPTO": _crypto_backend_name(),
    }

    library_versions_text = "\n".join(
        [f"➲ **{key}:** `{value}`" for key, value in library_versions.items()]
    )

    caption = f"""**HEY, I AM {BOT_NAME}**

━━━━━━ 🌟✿🌟 ━━━━━━
✪ **CREATOR:** [🄺🄰🅁🄼🄰](https://t.me/O_oKarma)

{library_versions_text}

➲ **PYTHON:** `{version_info[0]}.{version_info[1]}.{version_info[2]}`
➲ **BOT VERSION:** `2.1 Rx`
━━━━━━ 🌟✿🌟 ━━━━━━"""

    await message.reply_animation(
        random.choice(ALIVE_ANIMATION),
        caption=caption,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=ALIVE_BTN),
    )


# <=======================================================================================================>


# <================================================ NAME =======================================================>
__mod_name__ = "ALIVE"
# <================================================ END =======================================================>
