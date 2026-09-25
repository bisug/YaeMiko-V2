# Plugins

<p align="center">
  <a href="../README.md"><img alt="YaeMiko wordmark" src="assets/wordmark-dark.svg" width="420"></a>
</p>

Back to [README](../README.md).

## Contents

- [How plugins are discovered](#how-plugins-are-discovered)
- [Moderation](#moderation)
- [Chat configuration](#chat-configuration)
- [Members and onboarding](#members-and-onboarding)
- [Fun and media](#fun-and-media)
- [Information and diagnostics](#information-and-diagnostics)
- [Search, AI and translation](#search-ai-and-translation)
- [Reference data](#reference-data)
- [Disabled or feature flagged](#disabled-or-feature-flagged)
- [Writing a plugin](#writing-a-plugin)

## How plugins are discovered

`Mikobot/plugins/__init__.py` globs `*.py` in the plugin directory, drops `__init__.py`, applies
`LOAD` and `NO_LOAD`, and exports the result as `ALL_MODULES`. `Mikobot/__main__.py` imports every
name in that list, so dropping a new file into the directory is enough to register it.

57 modules are shipped. Names below are file names without the `.py` suffix, which is what `LOAD` and
`NO_LOAD` expect. The display name in `/help` comes from each module's `__mod_name__`.

## Moderation

| Module | Display name | Commands |
| --- | --- | --- |
| `admin` | ADMIN | `admincache`, `adminlist`, `promote`, `demote`, `fullpromote`, `title`, `invitelink`, `pin`, `unpin`, `unpinall` |
| `ban` | BAN | `kick`, `kickme`, `roar`, `unban` |
| `gban` | ANTI-SPAM | `antispam`, `gban`, `gbanlist`, `ungban` |
| `flood` | ANTI-FLOOD | `flood`, `setflood`, `setfloodmode` |
| `locks` | LOCKS | `lock`, `unlock`, `locks`, `locktypes` |
| `mute` | MUTE | `mute`, `unmute` |
| `warns` | WARN | `warns`, `addwarn`, `strongwarn`, `warnlimit` |
| `purge` | PURGE | Bulk message deletion |
| `zombies` | ZOMBIES | Removes accounts that left |
| `unbanall` | Unbanll | Lifts every ban in a chat |
| `blacklist` | BLACKLIST | `addblacklist`, `unblacklist`, `blacklist`, `blacklistmode` |
| `blacklist_stickers` | Stickers Blacklist | `blsticker`, `addblsticker`, `blstickermode` |
| `feds` | FEDS | Federation owner, admin and user help, plus `newfed`, `joinfed`, `leavefed`, `subfed`, `fban`, `fbanlist`, `unfban`, `importfbans`, `fbroadcast`, `fedinfo`, `frules`, `setfrules`, `fedchats`, `renamefed`, `delfed`, `setfedlog`, `unsetfedlog` |
| `approve` | APPROVALS | `approve`, `approved`, `unapprove`, `unapproveall`, `approval` |

## Chat configuration

| Module | Display name | Commands |
| --- | --- | --- |
| `chatadmin` | CHAT ADMIN | Anonymous admin actions, silent by default |
| `botadmins` | BOT-ADMIN | `botadmins` |
| `connection` | CONNECT | `connect`, `connection`, `disconnect`, `allowconnect`, `helpconnect` |
| `cust_filters` | FILTERS | `filter`, `filters`, `stop`, `removeallfilters` |
| `disable` | DISABLE | `disable`, `enable`, `disablemodule`, `enablemodule`, `listcmds` |
| `fsub` | F-SUB | Forced subscription enforcement |
| `nekomode` | NEKO | Anime themed reply markup |
| `rules` | RULES | `rules`, `setrules`, `clearrules` |
| `log_channel` | LOG-SET | `logchannel`, `setlog`, `unsetlog` |
| `extra` | EXTRA | `logs` and the extra command handler keyboards |

## Members and onboarding

| Module | Display name | Commands |
| --- | --- | --- |
| `welcome` | WELCOME | `setwelcome`, `resetwelcome`, `setgoodbye`, `resetgoodbye`, `cleanservice`, `cleanwelcome`, `welcome`, `goodbye`, `welcomemute`, plus help variants |
| `newuserinfo` | none | `/userinfo` for a member profile card |
| `afk` | AFK | `afk`, with a MongoDB backed clean mode cache |
| `notes` | NOTES | `save`, `get`, `clear`, `removeallnotes` |
| `users` | USERS | `groups` |
| `whispers` | WHISPER-MSG | Private whisper delivery over an inline query |

## Fun and media

| Module | Display name | Commands |
| --- | --- | --- |
| `fun` | FUN | `dare`, `truth`, `joke`, `rlg`, `decide`, `flirt`, `toss`, `roll`, `shrug`, `bluetext`, `weebify` |
| `couple` | COUPLE | Couple lookup |
| `cosplay` | none | `cosplay` search |
| `sangmata` | IMPOSTER | Character name recognition from photos |
| `stickers` | STICKERS | Sticker creation and conversion |
| `telegraph` | TELEGRAPH | Uploads media to Telegraph and returns the link |
| `hyperlink` | none | `hyperlink`, `pickwinner` |
| `imagegen` | IMAGE GENERATION DISABLED | Image generation, currently flagged off in the module display name |

## Information and diagnostics

| Module | Display name | Commands |
| --- | --- | --- |
| `ping` | none | `ping` |
| `alive` | ALIVE | Uptime card with `psutil` host statistics |
| `speedtest` | SpeedTest | `speedtest` |
| `info` | INFO | Chat and user information cards |
| `karma` | KARMA | Karma counters stored in MongoDB |

## Search, AI and translation

| Module | Display name | Commands |
| --- | --- | --- |
| `ai` | none | `askai`, `palm`, both routed through `google-genai` |
| `palmchat` | CHATBOT | Gemini backed chat |
| `search` | SEARCH | DuckDuckGo instant answers and Hacker News search |
| `quotely` | none | Quote generation |
| `reverse` | none | Reverse image search |
| `instadl` | none | Instagram media download |
| `tr` | TRANSLATOR | `echo` translation and `alphabet-detector` language guessing |
| `bug` | none | `/bug` report relay to the developer chat |

## Reference data

| Module | Display name | Commands |
| --- | --- | --- |
| `anime` | ANIME | Anime search, the module lineage from `lostb053` |
| `pokedex` | POKEDEX | `pokedex`, backed by [PokeAPI](https://pokeapi.co/) |
| `sports` | SPORTS | `cricket`, `football`, backed by [TheSportsDB](https://www.thesportsdb.com/) |
| `disasters` | Devs | `addsudo`, `addtiger`, runtime elevation helpers |

## Disabled or feature flagged

| Module | State |
| --- | --- |
| `imagegen` | `__mod_name__` is `IMAGE GENERATION DISABLED`, so it is skipped in the help listing until re-enabled |
| `chatbot.py.txt`, `getreaction.py.txt` | Renamed to `.txt`, so `glob` does not pick them up. Restore the `.py` extension to enable |

## Writing a plugin

```python
from telegram import Update
from telegram.constants import KeyboardButtonStyle
from telegram.ext import ContextTypes, CommandHandler

from Mikobot import function

__mod_name__ = "EXAMPLE"
__help__ = "Short description shown in /help."


async def example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello",
        reply_markup=None,
    )


function(CommandHandler("example", example))
```

Rules to follow:

1. File goes in `Mikobot/plugins/<name>.py`. It is registered automatically.
2. Set `__mod_name__` and `__help__` so the module renders correctly in `/help`.
3. Register handlers through `function(...)`, which is `dispatcher.add_handler`.
4. Give every inline button an explicit `style`: `PRIMARY` for navigation, `SUCCESS` for
   confirming actions, `DANGER` for destructive actions.
5. Store structured chat state in `Database/sql`, document shaped data in `Database/mongodb`.
6. Use the shared `state` httpx client from `Mikobot.state` for outbound HTTP.
7. Add a check to `tests/test_regressions.py` if the module fixes a regression.
