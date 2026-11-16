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
| `TOKEN` | string | Kurigram MTProto client session | From [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | integer | Rank checks | Parsed with `int()`, a bad value raises at startup |
| `DATABASE_URL` | string | `Database/sql` | `postgres://` and `postgresql://` are rewritten to `postgresql+psycopg://` |
| `EVENT_LOGS` | integer | Logging plugins | Channel ID for bot-level events |
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
| `DB_POOL_SIZE` | `min(8, cpu*2+4)` | Pooled connections held open |
| `DB_MAX_OVERFLOW` | `4` | Extra connections above the pool size |
| `DB_POOL_TIMEOUT` | `30` | Seconds a caller waits for a connection |
| `DB_PRE_PING` | `False` | Liveness check on each checkout, one round trip each; enable for proxies with a short idle timeout |
| `DB_CONNECT_TIMEOUT` | `10` | Seconds a connection attempt may take |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` | Milliseconds a single statement may run |
| `DB_LOCK_TIMEOUT_MS` | `2000` | Milliseconds a statement waits for a lock |
| `DB_IDLE_IN_TRANSACTION_MS` | `30000` | Milliseconds an open transaction may sit idle |
| `DB_STATEMENT_LOG_EVERY` | `500` | Statements between query mix log lines; `0` is not allowed |
| `LOGGER` | `True` | Unused, kept so existing deployments do not break. Log files are always written |
| `LOG_LEVEL` | `INFO` | Log level: `debug`, `info` (default), `warn`, `error` |
| `LOG_FORMAT` | `json` | `json` for production, `text` for human-readable local development |
| `ACTIVITY_LOG` | `True` | Log a summary line for every incoming update; set `False` to cut volume |
| `CATBOX_USERHASH` | empty | Optional user hash for Catbox uploads to authenticate and avoid datacenter IP blocks |
| `LITTERBOX_HOURS` | `72h` | Expiry duration for temporary Litterbox uploads (`1h`, `12h`, `24h`, `72h`) |
| `PREFERRED_LANGUAGE` | empty | Language code for anime synopsis and description translation |

An unrecognised `LOG_LEVEL` falls back to `INFO` instead of raising.

## User lists

All user lists accept space-separated numeric IDs. A non-numeric entry raises at startup rather than
being skipped, because a silently dropped admin is worse than a failed boot.

| Variable | Rank | Effect |
| --- | --- | --- |
| `DRAGONS` | Dragon | Admin level commands, merged with `DEV_USERS` |
| `DEV_USERS` | Dragon | Same as dragons |
| `DEMONS` | Demon | May run the global ban command |
| `WOLVES` | Wolf | Cannot be banned by the bot |
| `TIGERS` | Tiger | Never bannable |
| `BL_CHATS` | n/a | Space-separated blacklisted chat IDs |

`Mikobot/elevated_users.json` adds runtime users under the keys `sudos`, `supports`, `whitelists` and
`tigers`. The file also has `devs` and `spammers` keys that no code reads. The four active keys are
merged with the environment lists at import time, and `OWNER_ID` is always added to the dragon and
dev sets.

## Module selection

| Variable | Default | Behaviour |
| --- | --- | --- |
| `LOAD` | empty | Forces a start order. An unknown module name is fatal. |
| `NO_LOAD` | empty | Excludes modules by file name, without the `.py` suffix. |

Example: `LOAD="welcome rules warns"` boots those three first, `NO_LOAD="whispers zombies"` skips
those two entirely.

## Logging

All application code uses one shared logger in `Mikobot/logger.py`. `LOG_LEVEL` sets its minimum
level (`debug`, `info`, `warn`, `error`; an unrecognised value falls back to `info`).
`LOG_FORMAT=json` (the default, for production) writes one JSON object per entry with `timestamp`,
`level`, `message`, `service` and `correlation_id`; `LOG_FORMAT=text` renders the same fields as a
human-readable line. Output is queued, so a slow stream or disk never blocks the bot.

A rotating file handler is attached in addition to the stream handler. It is skipped when the
working directory is not writable, as it often is not on a container filesystem. `LOGGER` is
accepted for backwards compatibility but no longer read: log files are written whether it is set
or not. The `pyrogram` and `pyrate_limiter` loggers are pinned to `ERROR`, and `httpx` and
`httpcore` to `WARNING`, because their INFO output contains the complete Telegram API URL with
the bot token in the path.

Redaction rewrites tokens shaped like `bot<digits>:<20 or more characters>` to `bot<redacted>` and
bearer tokens to `Bearer <redacted>`. It masks known sensitive context fields (passwords, API
hashes, credentials, and similar) to `<redacted>`.

With `ACTIVITY_LOG=True` (the default), a raw-update handler emits an `Activity:` line at `INFO`
for every update the bot receives, including its type, chat, sender, and a message/command or
callback data summary. This is what makes the log show everything happening with the bot.
Errors and lifecycle events are logged regardless of this setting; set `ACTIVITY_LOG=False` to
suppress the per-update lines on a very busy bot.

## Where each value is read

| File | Reads |
| --- | --- |
| `Mikobot/__init__.py` | Everything the runtime needs, plus `ACTIVITY_LOG` |
| `Mikobot/logger.py` | `LOG_LEVEL`, `LOG_FORMAT` |
| `variables.py` | The `ENV` disabled path, class attributes read through `Config` |
| `Database/sql/__init__.py` | `DATABASE_URL` through `DB_URI` |
| `app.json` | The Heroku configuration manifest shown during deploy |
| `Infamous/karma.py` and `Mikobot/__main__.py` | `BOT_NAME`, `BOT_USERNAME`, `OWNER_ID`, `SUPPORT_CHAT` |
