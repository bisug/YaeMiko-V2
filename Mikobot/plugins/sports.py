import html
import os
from functools import partial
from urllib.parse import quote

from httpx import HTTPError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from Mikobot import function
from Mikobot.state import state

SPORTDB_KEY = os.getenv("SPORTDB_API_KEY", "123")
SPORTDB_URL = f"https://www.thesportsdb.com/api/v1/json/{SPORTDB_KEY}"
SPORTS = {"cricket": "Cricket", "football": "Soccer"}
MAX_LEAGUES = 10


async def _get_json(path: str) -> dict:
    response = await state.get(f"{SPORTDB_URL}/{path}")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


async def get_leagues(sport: str) -> list[dict]:
    data = await _get_json(f"search_all_leagues.php?s={quote(SPORTS[sport])}")
    leagues = data.get("countries") or []
    return [item for item in leagues if item.get("idLeague")][:MAX_LEAGUES]


async def get_matches(league_id: str) -> list[dict]:
    data = await _get_json(f"eventsnextleague.php?id={quote(str(league_id))}")
    return [item for item in (data.get("events") or []) if isinstance(item, dict)]


def _escape(value: object, limit: int = 300) -> str:
    return html.escape(str(value or "").replace("\n", " ").strip(), quote=False)[:limit]


def _format_match(match: dict, sport: str) -> str:
    icon = "🏏" if sport == "cricket" else "⚽"
    event = match.get("strEvent") or match.get("strEventAlternate") or "Match"
    date = match.get("strTimestamp") or match.get("dateEvent") or "Unknown"
    teams = match.get("strHomeTeam", "")
    away = match.get("strAwayTeam", "")
    teams_line = f"{_escape(teams)} vs {_escape(away)}" if teams and away else ""
    venue = _escape(match.get("strVenue"), 120)
    league = _escape(match.get("strLeague"), 120)
    lines = [
        f"{icon} <b>{_escape(event, 180)}</b>",
        f"🗓 <b>Date:</b> {_escape(date, 80)}",
    ]
    if teams_line:
        lines.append(f"🏆 <b>Teams:</b> {teams_line}")
    if venue and venue.lower() != "unknown":
        lines.append(f"🏟 <b>Venue:</b> {venue}")
    if league:
        lines.append(f"🏆 <b>Competition:</b> {league}")
    return "\n".join(lines)


def _league_keyboard(sport: str, leagues: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                _escape(item.get("strLeague"), 35),
                callback_data=f"sport_league:{sport}:{item['idLeague']}",
            )
        ]
        for item in leagues
    ]
    return InlineKeyboardMarkup(rows)


async def _show_leagues(update: Update, sport: str) -> None:
    message = update.effective_message
    try:
        leagues = await get_leagues(sport)
        if not leagues:
            await message.reply_text(f"No {sport} leagues are currently available.")
            return
        await message.reply_text(
            f"Select a {sport} league:",
            reply_markup=_league_keyboard(sport, leagues),
        )
    except HTTPError:
        await message.reply_text("TheSportsDB is unavailable. Please try again later.")
    except (ValueError, TypeError, KeyError):
        await message.reply_text("TheSportsDB returned incomplete league data.")


async def _send_league_message(message, sport: str, league_id: str) -> None:
    try:
        matches = await get_matches(league_id)
        if not matches:
            await message.reply_text(f"No upcoming {sport} matches found.")
            return
        text = "\n\n".join(_format_match(match, sport) for match in matches[:10])
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Leagues", callback_data=f"sport_menu:{sport}")]]
            ),
        )
    except HTTPError:
        await message.reply_text("TheSportsDB is unavailable. Please try again later.")
    except (ValueError, TypeError, KeyError):
        await message.reply_text("TheSportsDB returned incomplete match data.")



async def _send_league(update: Update, sport: str, league_id: str) -> None:
    query = update.callback_query
    await query.answer()
    try:
        matches = await get_matches(league_id)
        if not matches:
            await query.message.edit_text(f"No upcoming {sport} matches found.")
            return
        text = "\n\n".join(_format_match(match, sport) for match in matches[:10])
        await query.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Leagues", callback_data=f"sport_menu:{sport}")]]
            ),
        )
    except HTTPError:
        await query.message.edit_text("TheSportsDB is unavailable. Please try again later.")
    except (ValueError, TypeError, KeyError):
        await query.message.edit_text("TheSportsDB returned incomplete match data.")


async def _show_menu(update: Update, sport: str) -> None:
    query = update.callback_query
    await query.answer()
    try:
        leagues = await get_leagues(sport)
        if not leagues:
            await query.message.edit_text(f"No {sport} leagues are currently available.")
            return
        await query.message.edit_text(
            f"Select a {sport} league:",
            reply_markup=_league_keyboard(sport, leagues),
        )
    except HTTPError:
        await query.message.edit_text("TheSportsDB is unavailable. Please try again later.")
    except (ValueError, TypeError, KeyError):
        await query.message.edit_text("TheSportsDB returned incomplete league data.")


async def get_sport_matches(update: Update, context: ContextTypes.DEFAULT_TYPE, sport: str) -> None:
    if not update.effective_message:
        return
    if len(context.args) == 1 and context.args[0].isdigit():
        await _send_league_message(update.effective_message, sport, context.args[0])
    else:
        await _show_leagues(update, sport)


async def sport_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data.startswith("sport_"):
        return
    parts = query.data.split(":")
    try:
        if parts[1] == "menu":
            await _show_menu(update, parts[2])
        else:
            await _send_league(update, parts[1], parts[2])
    except (IndexError, ValueError):
        await query.answer("Invalid selection.", show_alert=True)


function(CommandHandler("cricket", partial(get_sport_matches, sport="cricket")))
function(CommandHandler("football", partial(get_sport_matches, sport="football")))
function(CallbackQueryHandler(sport_callback, pattern=r"^sport_(?:league|menu):", block=False))

__help__ = """
🏅 <b>Sports schedules</b>

➠ <b>Commands:</b>
» /cricket — list cricket leagues
» /football — list football leagues
» /cricket &lt;league ID&gt; — show upcoming cricket matches
» /football &lt;league ID&gt; — show upcoming football matches

Data: TheSportsDB
"""

__mod_name__ = "SPORTS"
