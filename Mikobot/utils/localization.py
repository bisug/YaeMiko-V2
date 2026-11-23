import inspect
import json
from functools import partial, wraps
from pathlib import Path

from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, InlineQuery, Message

from Database.sql.locale_sql import get_db_lang

enabled_locales: list[str] = [
    # "en-GB",  # English (United Kingdom)
    "en-US",  # English (United States)
    # "pt-BR",  # Portuguese (Brazil)
    # "es-ES",  # Spanish
    # "fr-FR",  # French
    # "de-DE",  # German
    # "it-IT",  # Italian
    # "nl-NL",  # Dutch
    # "ar-SA",  # Arabic
    # "ckb-IR",  # Sorani (Kurdish)
    # "fi-FI",  # Finnish
    # "he-IL",  # Hebrew
    "id-ID",  # Indonesian
    "id-JW",  # Javanese
    # "ja-JP",  # Japanese
    # "no-NO",  # Norwegian
    # "pl-PL",  # Polish
    # "pt-BRe",  # Portuguese (Brazil, extended version)
    # "pt-BR2",  # Portuguese (Brazil, informal version)
    # "ro-RO",  # Romanian
    # "ru-RU",  # Russian
    # "sv-SE",  # Swedish
    # "tr-TR",  # Turkish
    # "uk-UA",  # Ukrainian
    # "zh-CN",  # Chinese (Simplified)
    # "zh-TW",  # Chinese (Traditional)
]

default_language: str = "en-US"


def cache_localizations(files: list[Path]) -> dict[str, dict[str, dict[str, str]]]:
    ldict = {lang: {} for lang in enabled_locales}
    for file in files:
        lname = file.parent.name
        pname = file.stem
        with file.open(encoding="utf-8") as source:
            dic = json.load(source)
        dic.update(ldict[lname].get(pname, {}))
        ldict[lname][pname] = dic
    return ldict


jsons: list[Path] = []

for locale in enabled_locales:
    jsons += list(Path("locales", locale).glob("*.json"))

langdict = cache_localizations(jsons)


def get_locale_string(
    dic: dict, language: str, default_context: str, key: str, context: str = None
) -> str:
    if context:
        default_context = context
        dic = langdict[language].get(context, langdict[default_language][context])
    res: str = (
        dic.get(key) or langdict[default_language][default_context].get(key) or key
    )
    return res


async def get_lang(message) -> str:
    if isinstance(message, CallbackQuery):
        chat = message.message.chat
    elif isinstance(message, Message):
        chat = message.chat
    elif isinstance(message, InlineQuery):
        chat, chat.type = message.from_user, ChatType.PRIVATE
    else:
        raise TypeError(f"Update type '{message.__name__}' is not supported.")

    lang = get_db_lang(chat.id)

    if chat.type == ChatType.PRIVATE:
        lang = lang or message.from_user.language_code or default_language
    else:
        lang = lang or default_language
    # Some language codes have no hyphen.
    if len(lang.split("-")) == 1:
        # Match a locale that starts with the provided code.
        for locale_ in enabled_locales:
            if locale_.startswith(lang):
                lang = locale_
    elif lang.split("-")[1].islower():
        lang = lang.split("-")
        lang[1] = lang[1].upper()
        lang = "-".join(lang)
    return lang if lang in enabled_locales else default_language


def use_chat_lang(context: str = None):
    if not context:
        cwd = Path.cwd()
        frame = inspect.stack()[1]

        fname = Path(frame.filename)

        if fname.is_relative_to(cwd):
            fname = fname.relative_to(cwd)
        context = Path(fname.parts[2]).stem

    def decorator(func):
        @wraps(func)
        async def wrapper(client, message):
            lang = await get_lang(message)

            dic = langdict.get(lang, langdict[default_language])

            lfunc = partial(get_locale_string, dic.get(context, {}), lang, context)
            return await func(client, message, lfunc)

        return wrapper

    return decorator
