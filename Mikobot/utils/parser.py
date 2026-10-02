# <============================================== IMPORTS =========================================================>
from html import escape
from re import sub

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def escape_markdown(text: str) -> str:
    """Escape markdown data."""
    escape_chars = r"\*_`\["
    return sub(r"([%s])" % escape_chars, r"\\\1", text)


def mention_html(user_id: int, name: str) -> str:
    """Mention user in html format.

    Synchronous and id-first because every caller builds log and chat text by
    interpolating the result: PTB's `await mention_html(name, user_id)` was
    ported to a plain call with the arguments transposed, which both dropped the
    await and fed the id into escape(). The name is escaped here, so callers
    must pass it raw.
    """
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def mention_markdown(user_id: int, name: str) -> str:
    """Mention user in markdown format. Escapes the name; callers pass it raw."""
    return f"[{escape_markdown(name)}](tg://user?id={user_id})"


# <================================================ END =======================================================>
