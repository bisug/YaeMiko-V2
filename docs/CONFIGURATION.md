# Configuration

<p align="center">
  <a href="../README.md"><img alt="YaeMiko wordmark" src="assets/wordmark-dark.svg" width="420"></a>
</p>

Back to [README](../README.md).

## Contents

- [Sources and precedence](#sources-and-precedence)
- [Required variables](#required-variables)
- [Optional variables](#optional-variables)
- [User lists](#user-lists)
- [Module selection](#module-selection)
- [Logging](#logging)
- [AI features](#ai-features)
- [Where each value is read](#where-each-value-is-read)

## Sources and precedence

Configuration is resolved in this order, first hit wins:

1. Process environment variables.
2. `.env` in the project root, read by `_load_local_env()`. Existing environment variables are
   never overwritten.
3. `variables.py` classes `Config`, `Production` and `Development`, used only when `ENV` is falsy.

`ENV` selects between path 2 and 3. Set `ENV` to any truthy value such as `True` or `1` to use
environment variables.

## Required variables

| Variable | Type | Used by | Notes |
| --- | --- | --- | --- |
| `API_ID` | integer | Kurigram client | From [my.telegram.org/apps](https://my.telegram.org/apps) |
| `API_HASH` | string | Kurigram client | Same page |
| `TOKEN` | string | PTB application and Kurigram bot session | From [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | integer | Rank checks | Parsed with `int()`, a bad value raises at startup |
| `DATABASE_URL` | string | `Database/sql` | `postgres://` is rewritten to `postgresql+psycopg://` |
| `MONGO_DB_URI` | string | `Database/mongodb` | Atlas SRV string |
| `DB_NAME` | string | `Database/mongodb` | Mongo database name |
| `EVENT_LOGS` | integer | Logging plugins | Channel ID for bot level events |
| `MESSAGE_DUMP` | integer | Logging plugins | Dump chat ID |
| `SUPPORT_CHAT` | string | Start and about keyboards | Username without the `@` |
| `SUPPORT_ID` | integer | Boot message | Numeric support chat ID |

## Optional variables

| Variable | Default | Description |
| --- | --- | --- |
| `ALLOW_CHATS` | `True` | Accept private chat usage |
| `ALLOW_EXCL` | `True` | Accept excluded chat usage |
| `DEL_CMDS` | `True` | Delete command messages from unprivileged users |
| `INFOPIC` | `True` | Use the image info card instead of a text card |
| `STRICT_GBAN` | `True` | Enforce global bans in new groups |
| `BAN_STICKER` | empty | Sticker file ID banned in every group |
| `TEMP_DOWNLOAD_DIRECTORY` | `./` | Scratch directory for downloaded media |
| `LOGGER` | `True` | Write rotating log files |
| `LOG_LEVEL` | `INFO` | Root log level, one of `CRITICAL ERROR WARNING INFO DEBUG NOTSET` |
| `ACTIVITY_LOG` | `False` | Log a summary line for every incoming update |

An unrecognised `LOG_LEVEL` falls back to `INFO` instead of raising.

## User lists

All user lists accept space separated numeric IDs. A non numeric entry raises at startup rather than
being skipped, because a silently dropped admin is worse than a failed boot.

| Variable | Rank | Effect |
| --- | --- | --- |
| `DRAGONS` | Dragon | Admin level commands, merged with `DEV_USERS` |
| `DEV_USERS` | Dragon | Same as dragons |
| `DEMONS` | Demon | May run the global ban command |
| `WOLVES` | Wolf | Cannot be banned by the bot |
| `TIGERS` | Tiger | Never bannable |
| `BL_CHATS` | n/a | Space separated blacklisted chat IDs |

`Mikobot/elevated_users.json` adds runtime users under the keys `devs`, `supports`, `whitelists`,
`sudos`, `tigers` and `spammers`. The file is merged with the environment lists at import time, and
`OWNER_ID` is always added to the dragon and dev sets.

## Module selection

| Variable | Default | Behaviour |
| --- | --- | --- |
| `LOAD` | empty | Forces a start order. An unknown module name is fatal. |
| `NO_LOAD` | empty | Excludes modules by file name, without the `.py` suffix. |

Example: `LOAD="welcome rules warns"` boots those three first, `NO_LOAD="whispers zombies"` skips
those two entirely.

## Logging

`LOGGER=True` attaches a rotating file handler through `logging.handlers.RotatingFileHandler` in
addition to the stream handler. `LOG_LEVEL` controls the root level, and the `pyrogram` and
`pyrate_limiter` loggers are pinned to `ERROR`.

`RedactingFormatter` rewrites any token shaped like `bot<digits>:<30 or more characters>` to
`bot<redacted>`. The `httpx` and `httpcore` loggers are set to `WARNING` because their INFO output
contains the complete Telegram API URL with the token in the path.

## AI features

| Variable | Default | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | empty | Enables `/askai` and `/palm`. Empty means the commands reply with a configuration notice. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model id passed to `google-genai` |

A retired `gemini-2.5-flash-lite` value is replaced with `gemini-3.5-flash-lite` and a warning is
logged at import time.

## Where each value is read

| File | Reads |
| --- | --- |
| `Mikobot/__init__.py` | Everything the runtime needs, plus `LOG_LEVEL` and `ACTIVITY_LOG` |
| `variables.py` | The `ENV` disabled path, class attributes read through `Config` |
| `Database/sql/__init__.py` | `DATABASE_URL` through `DB_URI` |
| `Database/mongodb/mongodb.py` | `MONGO_DB_URI` and `DB_NAME` |
| `app.json` | The Heroku configuration manifest shown during deploy |
| `Infamous/karma.py` and `Mikobot/__main__.py` | `BOT_NAME`, `BOT_USERNAME`, `OWNER_ID`, `SUPPORT_CHAT` |
