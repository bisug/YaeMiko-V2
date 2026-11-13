# <============================================== IMPORTS =========================================================>
import random

from pyrogram.enums import ParseMode
from pyrogram.types import Message

import Mikobot.utils.fun_strings as fun_strings
from Mikobot.events import on_message
from Mikobot.plugins.disable import disableable
from Mikobot.state import state

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def make_request(url: str) -> str:
    response = await state.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("The question service returned an invalid response.")
    return question.strip()[:1000]


async def truth(client, message: Message):
    try:
        question = await make_request("https://api.truthordarebot.xyz/v1/truth")
    except Exception:
        question = "The truth service is unavailable. Please try again later."
    await message.reply_text(question)


async def dare(client, message: Message):
    try:
        question = await make_request("https://api.truthordarebot.xyz/v1/dare")
    except Exception:
        question = "The dare service is unavailable. Please try again later."
    await message.reply_text(question)


async def joke(client, message: Message):
    from pyjokes import get_joke

    await message.reply_text(get_joke())


async def roll(client, message: Message):
    await message.reply_text(str(random.choice(range(1, 7))))


async def flirt(client, message: Message):
    await message.reply_text(random.choice(fun_strings.FLIRT))


async def toss(client, message: Message):
    await message.reply_text(random.choice(fun_strings.TOSS))


async def shrug(client, message: Message):
    # A reply to a message answers that message, otherwise this one.
    target = message.reply_to_message or message
    await target.reply_text(r"¯\_(ツ)_/¯")


async def bluetext(client, message: Message):
    target = message.reply_to_message or message
    await target.reply_text(
        "/BLUE /TEXT\n/MUST /CLICK\n/I /AM /A /STUPID /ANIMAL /THAT /IS /ATTRACTED /TO /COLORS"
    )


async def rlg(client, message: Message):
    eyes = random.choice(fun_strings.EYES)
    mouth = random.choice(fun_strings.MOUTHS)
    ears = random.choice(fun_strings.EARS)

    left, right = (eyes + [eyes[0]])[:2]
    repl = ears[0] + left + mouth[0] + right + ears[1]
    await message.reply_text(repl)


async def decide(client, message: Message):
    target = message.reply_to_message or message
    await target.reply_text(random.choice(fun_strings.DECIDE))


normiefont = [
    "a",
    "b",
    "c",
    "d",
    "e",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "n",
    "o",
    "p",
    "q",
    "r",
    "s",
    "t",
    "u",
    "v",
    "w",
    "x",
    "y",
    "z",
]

weebyfont = [
    "卂",
    "乃",
    "匚",
    "刀",
    "乇",
    "下",
    "厶",
    "卄",
    "工",
    "丁",
    "长",
    "乚",
    "从",
    "𠘨",
    "口",
    "尸",
    "㔿",
    "尺",
    "丂",
    "丅",
    "凵",
    "リ",
    "山",
    "乂",
    "丫",
    "乙",
]


async def webify(client, message: Message):
    args = message.command[1:]
    string = ""

    if message.reply_to_message:
        text = message.reply_to_message.text
        if not text:
            await message.reply_text("Reply to a text message to use /weebify.")
            return
        string = text.lower().replace(" ", "  ")

    if args:
        string = "  ".join(args).lower()

    if not string:
        await message.reply_text(
            "Usage is `/weebify <text>`", parse_mode=ParseMode.MARKDOWN
        )
        return

    for normiecharacter in string:
        if normiecharacter in normiefont:
            weebycharacter = weebyfont[normiefont.index(normiecharacter)]
            string = string.replace(normiecharacter, weebycharacter)

    if message.reply_to_message:
        await message.reply_to_message.reply_text(string)
    else:
        await message.reply_text(string)


# <=================================================== HELP ====================================================>


__help__ = """
» /decide: randomly answers yes/no/maybe.

» /truth: sends a random truth string.

» /dare: sends a random dare string.

» /toss: tosses a coin.

» /shrug: get shrug xd.

» /bluetext: check yourself :V.

» /roll: roll a dice.

» /rlg: join ears, nose, mouth and create an emo ;-;

» /weebify <text>: returns a weebified text.

» /flirt: returns a random flirt line.

» /joke: tells a random joke.
"""

# <================================================ HANDLER =======================================================>
# Eleven single-purpose commands; the loop keeps them from needing eleven
# near-identical registration lines.
for _name, _callback in (
    ("roll", roll),
    ("toss", toss),
    ("shrug", shrug),
    ("bluetext", bluetext),
    ("rlg", rlg),
    ("decide", decide),
    ("weebify", webify),
    ("flirt", flirt),
    ("truth", truth),
    ("dare", dare),
    ("joke", joke),
):
    on_message(*disableable(_name), chained=True)(_callback)

# <================================================ END =======================================================>
