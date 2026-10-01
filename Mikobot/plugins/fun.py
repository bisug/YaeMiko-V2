# <============================================== IMPORTS =========================================================>
import random

from aiogram.enums import ParseMode
from aiogram.filters import CommandObject
from aiogram.types import Message

import Mikobot.utils.fun_strings as fun_strings
from Mikobot import dp
from Mikobot.plugins.disable import disableable
from Mikobot.state import state
from Mikobot.utils.gate import chain

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


async def truth(message: Message):
    try:
        question = await make_request("https://api.truthordarebot.xyz/v1/truth")
    except Exception:
        question = "The truth service is unavailable. Please try again later."
    await message.answer(question)


async def dare(message: Message):
    try:
        question = await make_request("https://api.truthordarebot.xyz/v1/dare")
    except Exception:
        question = "The dare service is unavailable. Please try again later."
    await message.answer(question)


async def joke(message: Message):
    from pyjokes import get_joke

    await message.answer(get_joke())


async def roll(message: Message):
    await message.answer(random.choice(range(1, 7)))


async def flirt(message: Message):
    await message.answer(random.choice(fun_strings.FLIRT))


async def toss(message: Message):
    await message.answer(random.choice(fun_strings.TOSS))


async def shrug(message: Message):
    msg = message
    reply_text = (
        msg.reply_to_message.answer if msg.reply_to_message else msg.answer
    )
    await reply_text(r"¯\_(ツ)_/¯")


async def bluetext(message: Message):
    msg = message
    reply_text = (
        msg.reply_to_message.answer if msg.reply_to_message else msg.answer
    )
    await reply_text(
        "/BLUE /TEXT\n/MUST /CLICK\n/I /AM /A /STUPID /ANIMAL /THAT /IS /ATTRACTED /TO /COLORS"
    )


async def rlg(message: Message):
    eyes = random.choice(fun_strings.EYES)
    mouth = random.choice(fun_strings.MOUTHS)
    ears = random.choice(fun_strings.EARS)

    left, right = (eyes + [eyes[0]])[:2]
    repl = ears[0] + left + mouth[0] + right + ears[1]
    await message.answer(repl)


async def decide(message: Message):
    reply_text = (
        message.reply_to_message.answer
        if message.reply_to_message
        else message.answer
    )
    await reply_text(random.choice(fun_strings.DECIDE))


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


async def webify(message: Message, command: CommandObject):
    args = command.args or []
    string = ""

    if message.reply_to_message:
        text = message.reply_to_message.text
        if not text:
            await message.answer("Reply to a text message to use /weebify.")
            return
        string = text.lower().replace(" ", "  ")

    if args:
        string = "  ".join(args).lower()

    if not string:
        await message.answer(
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
        await message.answer(string)


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
    dp.message.register(chain(_callback), *disableable(_name))

# <================================================ END =======================================================>
