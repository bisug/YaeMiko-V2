<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/wordmark-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/wordmark-light.svg">
  <img alt="YaeMiko wordmark" src="docs/assets/wordmark-dark.svg" width="560">
</picture>

[![Python](https://img.shields.io/badge/python-3.14-blueviolet?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blueviolet?style=for-the-badge)](https://github.com/bisug/YaeMiko-V2/blob/main/LICENSE)
[![python-telegram-bot](https://img.shields.io/badge/PTB-22.8-2AABEE?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/python-telegram-bot/)
[![Kurigram](https://img.shields.io/badge/Kurigram-2.2.26-2AABEE?style=for-the-badge&logo=python&logoColor=white)](https://pypi.org/project/Kurigram/)
[![TgCryptoRust](https://img.shields.io/badge/TgCryptoRust-1.3.1-2AABEE?style=for-the-badge&logo=rust&logoColor=white)](https://pypi.org/project/TgCryptoRust/)
[![Docker](https://img.shields.io/badge/docker-multistage-2496ED?style=for-the-badge&logo=docker&logoColor=white)](Dockerfile)
[![Heroku](https://img.shields.io/badge/deploy-heroku-79589F?style=for-the-badge&logo=heroku&logoColor=white)](https://dashboard.heroku.com/apps/new?template=https://github.com/bisug/YaeMiko-V2)
[![CI](https://img.shields.io/github/actions/workflow/status/bisug/YaeMiko-V2/ci.yml?branch=main&style=for-the-badge&label=CI&color=4c1)](https://github.com/bisug/YaeMiko-V2/actions/workflows/ci.yml)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/bisug/YaeMiko-V2/codeql.yml?branch=main&style=for-the-badge&label=CodeQL&color=8957e5)](https://github.com/bisug/YaeMiko-V2/actions/workflows/codeql.yml)

[![stars](https://img.shields.io/github/stars/bisug/YaeMiko-V2?style=for-the-badge&logo=github&label=stars)](https://github.com/bisug/YaeMiko-V2/stargazers)
[![forks](https://img.shields.io/github/forks/bisug/YaeMiko-V2?style=for-the-badge&logo=github&label=forks)](https://github.com/bisug/YaeMiko-V2/network/members)
[![issues](https://img.shields.io/github/issues/bisug/YaeMiko-V2?style=for-the-badge&logo=github&label=issues)](https://github.com/bisug/YaeMiko-V2/issues)
[![last-commit](https://img.shields.io/github/last-commit/bisug/YaeMiko-V2?style=for-the-badge&logo=github&label=last%20commit)](https://github.com/bisug/YaeMiko-V2/commits/main)

[![telegram](https://img.shields.io/badge/telegram-bot-2AABEE?style=for-the-badge&logo=telegram&logoColor=white)](https://telegram.org/)

</div>

<p align="center">
  <a href="#highlights">Highlights</a> &nbsp; | &nbsp;
  <a href="#architecture">Architecture</a> &nbsp; | &nbsp;
  <a href="#tech-stack">Tech stack</a> &nbsp; | &nbsp;
  <a href="#plugin-catalogue">Plugins</a> &nbsp; | &nbsp;
  <a href="#configuration">Configuration</a> &nbsp; | &nbsp;
  <a href="#deployment">Deployment</a> &nbsp; | &nbsp;
  <a href="docs/ARCHITECTURE.md">Deep dive</a>
</p>

---

# YaeMiko

**YaeMiko** is a modular Telegram group management bot that runs two Telegram clients in a single
process: [python-telegram-bot](https://docs.python-telegram-bot.org/) for the Bot API and
[Kurigram](https://docs.kurigram.live/) for MTProto features. It targets Python 3.14, stores chat
state in PostgreSQL and document shaped data in MongoDB, and ships 57 plugin modules.

| | |
| --- | --- |
| **Runtime** | Python 3.14.7, single `asyncio` event loop, long polling |
| **Telegram** | PTB 22.8 on the Bot API, Kurigram 2.2.26 on MTProto, side by side |
| **Storage** | PostgreSQL 16 through SQLAlchemy 2.1, MongoDB through PyMongo 4.18 |
| **Modules** | 57 auto discovered plugins under `Mikobot/plugins` |
| **Deployment** | Heroku worker dyno, Docker, or bare VPS |
| **Guarantees** | CI compile, unit, JSON and whitespace gates, weekly CodeQL, Dependabot updates |

> **Maintained fork.** This repository is the main home of YaeMiko and is forked from
> [Infamous-Hydra/YaeMiko](https://github.com/Infamous-Hydra/YaeMiko). Upstream remains credited
> under [Credits](#credits) and in the MIT [LICENSE](LICENSE).

---

## Highlights

- **Dual client, one process.** Bot API and MTProto are both live. Commands that need user to user
  features run on Kurigram, everything else stays on PTB.
- **Semantic inline buttons.** Every inline button declares an explicit style: `PRIMARY` for
  navigation, `SUCCESS` for confirming and positive actions, `DANGER` for destructive actions. A
  regression test parses the AST and fails the build if any button is missing one.
- **Rate limiting and persistence.** `AIORateLimiter` throttles outbound calls and
  `PicklePersistence` keeps chat and user context across restarts, so a dyno bounce does not lose
  conversation state.
- **Token safe logging.** A `RedactingFormatter` strips anything shaped like a bot token, and the
  `httpx` and `httpcore` loggers are pinned to `WARNING` because their INFO output contains the
  full Telegram API URL.
- **Dual store design.** Structured chat state lives in PostgreSQL, user profiles, chats, AFK
  entries, whispers and karma live in MongoDB.
- **Deploy anywhere.** The same `python -m Mikobot` entry point runs on Heroku, in the multi stage
  Docker image, or on a plain VPS.
- **Modular by drop in.** Plugins are discovered with `glob`; `LOAD` controls ordering and
  `NO_LOAD` excludes modules, so no code change is needed to trim the bot.

---

## Architecture

![YaeMiko runtime architecture](docs/assets/architecture.svg)

Full walkthrough: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Layer | Path | Responsibility |
| --- | --- | --- |
| Entry point | [`Mikobot/__main__.py`](Mikobot/__main__.py) | Handler registration, plugin discovery, chat migration, graceful shutdown |
| Core runtime | [`Mikobot/__init__.py`](Mikobot/__init__.py) | Configuration, logging, event loop, PTB application, Kurigram client |
| Plugin bus | [`Mikobot/events.py`](Mikobot/events.py) | Registers Kurigram handlers behind one signature |
| HTTP client | [`Mikobot/state.py`](Mikobot/state.py) | One shared `httpx.AsyncClient` with HTTP/2 and a 20 second timeout |
| Plugins | [`Mikobot/plugins`](Mikobot/plugins) | 57 feature modules, auto discovered |
| SQL layer | [`Database/sql`](Database/sql) | 29 SQLAlchemy modules backed by PostgreSQL |
| Mongo layer | [`Database/mongodb`](Database/mongodb) | 10 collection modules plus a shared client |
| Shared helpers | [`Mikobot/utils`](Mikobot/utils), [`Mikobot/plugins/helper_funcs`](Mikobot/plugins/helper_funcs) | Parsers, permissions, caching, extraction, localization |
| Static assets | [`Extra`](Extra), [`locales`](locales) | Fonts, default avatars, catalogs for `en-US`, `id-ID`, `id-JW` |

### Startup sequence

1. `Mikobot/__init__.py` loads `.env` when present, then reads configuration from the environment
   when `ENV` is truthy, otherwise from [`variables.py`](variables.py).
2. Logging is configured with token redaction, a stream handler, and an optional rotating file
   handler.
3. The `asyncio` event loop is created and the PTB `Application` is built with
   `concurrent_updates(64)`, `AIORateLimiter()` and `PicklePersistence`.
4. The bot is initialized and `get_me()` supplies `BOT_ID`, `BOT_NAME` and `BOT_USERNAME`, so the
   display name is never hardcoded.
5. The Kurigram `Client` is created and a boot message is pushed to the support chat.
6. `Mikobot/__main__.py` registers the core handlers, imports every module listed by `ALL_MODULES`,
   and starts long polling.
7. On exit the Kurigram client, the MongoDB client, the httpx client and the loop are closed in
   order.

---

## Update handling flow

![Update handling flow](docs/assets/update-flow.svg)

Every update travels the same path: transport, handler match, permission gate, rate limiter,
execution. Persistence, reply construction and error handling surround that spine.

---

## Tech stack

### Language and runtime

| Component | Version | Link |
| --- | --- | --- |
| Python | 3.14.7 | [python.org](https://www.python.org/) |
| asyncio event loop | stdlib | [docs](https://docs.python.org/3/library/asyncio.html) |
| Pinned interpreter | `python-3.14.7` | [.python-version](.python-version) |

### Telegram clients

| Component | Version | Link |
| --- | --- | --- |
| python-telegram-bot | 22.8 | [PyPI](https://pypi.org/project/python-telegram-bot/) |
| Kurigram | 2.2.26 | [PyPI](https://pypi.org/project/Kurigram/) |
| TgCryptoRust | 1.3.1 | [PyPI](https://pypi.org/project/TgCryptoRust/) |
| AIORateLimiter | bundled with PTB | [docs](https://docs.python-telegram-bot.org/en/stable/telegram.ext.aioratelimiter.html) |
| PicklePersistence | bundled with PTB | [docs](https://docs.python-telegram-bot.org/en/stable/telegram.ext.picklepersistence.html) |
| KeyboardButtonStyle | bundled with PTB | [docs](https://docs.python-telegram-bot.org/en/stable/telegram.constants.html) |

### Data stores

| Component | Version | Link |
| --- | --- | --- |
| PostgreSQL | 16 (Heroku addon) | [postgresql.org](https://www.postgresql.org/) |
| SQLAlchemy | 2.1.0 | [sqlalchemy.org](https://www.sqlalchemy.org/) |
| psycopg (binary, pool) | 3.3.6 | [psycopg.org](https://www.psycopg.org/) |
| MongoDB Atlas | free or serverless tier | [mongodb.com](https://www.mongodb.com/atlas) |
| PyMongo | 4.18.2 | [PyPI](https://pypi.org/project/pymongo/) |

### HTTP, media and processing

| Component | Version | Purpose | Link |
| --- | --- | --- | --- |
| httpx with HTTP/2 | 0.28.1 | Shared async HTTP client | [PyPI](https://pypi.org/project/httpx/) |
| google-genai | latest | `/askai` and `/palm` | [Gemini API](https://ai.google.dev/gemini-api) |
| Pillow | 12.3.0 | Image composition and text rendering | [PyPI](https://pypi.org/project/pillow/) |
| ONNX Runtime | 1.30.0 | NSFW detection inference | [PyPI](https://pypi.org/project/onnxruntime/) |
| opennsfw-onnx | 0.1.0 | Pre trained NSFW classifier | [PyPI](https://pypi.org/project/opennsfw-onnx/) |
| beautifulsoup4 | 4.15.0 | HTML scraping for search modules | [PyPI](https://pypi.org/project/beautifulsoup4/) |
| cachetools | 7.2.0 | Short lived caching in hot paths | [PyPI](https://pypi.org/project/cachetools/) |
| pyrate-limiter | 4.5.0 | Extra outbound throttling | [PyPI](https://pypi.org/project/pyrate-limiter/) |
| psutil | 7.2.2 | Runtime and host stats for `/alive` | [PyPI](https://pypi.org/project/psutil/) |
| speedtest-cli | 2.1.3 | Bandwidth checks | [PyPI](https://pypi.org/project/speedtest-cli/) |
| Telegraph | 2.2.0 | Image hosting for `/telegraph` | [PyPI](https://pypi.org/project/telegraph/) |
| ffmpeg | system package | Media muxing in the Docker image | [ffmpeg.org](https://ffmpeg.org/) |

### Text and localization

| Component | Version | Purpose | Link |
| --- | --- | --- | --- |
| Unidecode | 1.4.0 | Transliteration for search and fonts | [PyPI](https://pypi.org/project/unidecode/) |
| alphabet-detector | 0.0.7 | Language guessing for `/tr` | [PyPI](https://pypi.org/project/alphabet-detector/) |
| humanize | 4.16.0 | Relative timestamps | [PyPI](https://pypi.org/project/humanize/) |
| locales | bundled | `en-US`, `id-ID`, `id-JW` catalogs | [locales](locales) |

### Tooling

| Tool | Purpose | Link |
| --- | --- | --- |
| GitHub Actions CI | Compile, unit tests, JSON validation, whitespace, Docker build | [ci.yml](.github/workflows/ci.yml) |
| CodeQL | Weekly and push security scanning | [codeql.yml](.github/workflows/codeql.yml) |
| Dependabot | Weekly pip and Actions updates | [dependabot.yml](.github/dependabot.yml) |
| unittest | Dependency free regression suite | [tests/test_regressions.py](tests/test_regressions.py) |

---

## Repository layout

```text
YaeMiko/
├── Mikobot/                     Application package
│   ├── __init__.py              Config, logging, event loop, PTB app, Kurigram client
│   ├── __main__.py              Handler registration and entry point
│   ├── events.py                Kurigram handler registration helpers
│   ├── state.py                 Shared httpx client
│   ├── elevated_users.json      Runtime elevated user additions
│   ├── plugins/                 57 feature modules + helper_funcs
│   └── utils/                   Parsers, permissions, caching, localization
├── Database/
│   ├── mongodb/                 10 PyMongo collection modules + client
│   └── sql/                     29 SQLAlchemy modules
├── Infamous/                    Static start and repo keyboards
├── Extra/                       Fonts and default images
├── locales/                     en-US, id-ID, id-JW catalogs
├── tests/                       unittest regression suite
├── docs/                        Documentation and SVG diagrams
│   ├── ARCHITECTURE.md
│   ├── CONFIGURATION.md
│   ├── PLUGINS.md
│   └── assets/
│       ├── architecture.svg
│       ├── update-flow.svg
│       ├── wordmark-dark.svg
│       └── wordmark-light.svg
├── .github/workflows/           CI and CodeQL
├── app.json                     Heroku app manifest
├── Dockerfile                   Multi stage image
├── heroku.yml                   Heroku Docker build and run
├── Procfile                     Heroku worker entry
├── requirements.txt             Pinned dependencies
└── variables.py                 Fallback configuration for non ENV setups
```

---

## Plugin catalogue

57 modules are discovered automatically. Per module summaries live in
[docs/PLUGINS.md](docs/PLUGINS.md).

| Group | Modules |
| --- | --- |
| Moderation | `admin`, `ban`, `blacklist`, `blacklist_stickers`, `feds`, `flood`, `gban`, `locks`, `mute`, `purge`, `unbanall`, `warns`, `zombies` |
| Chat control | `approve`, `botadmins`, `chatadmin`, `connection`, `cust_filters`, `disable`, `fsub`, `nekomode`, `rules` |
| Welcome and identity | `afk`, `newuserinfo`, `notes`, `users`, `welcome`, `whispers` |
| Fun and media | `cosplay`, `couple`, `fun`, `hyperlink`, `imagegen`, `sangmata`, `stickers`, `telegraph` |
| Information | `alive`, `info`, `karma`, `log_channel`, `ping`, `speedtest` |
| Search, AI and translation | `ai`, `bug`, `instadl`, `palmchat`, `pkang`, `quotely`, `reverse`, `search`, `tr` |
| Reference data | `anime`, `disasters`, `pokedex`, `sports` |

`LOAD` forces a start order and `NO_LOAD` skips modules entirely. Both accept a space separated list
of module file names without the `.py` suffix.

---

## Configuration

Two configuration paths exist.

**Environment driven.** Set `ENV` to any truthy value and every value is read from the process
environment or a `.env` file in the project root. This is the Heroku and Docker path.

**File driven.** Leave `ENV` unset and values come from [`variables.py`](variables.py).

Full reference with defaults and elevated user ranks:
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

### Required

| Variable | Description | Example |
| --- | --- | --- |
| `API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org/apps) | `123456` |
| `API_HASH` | Telegram API hash from the same page | `0123456789abcdef0123456789abcdef` |
| `TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) | `123456:AA...` |
| `OWNER_ID` | Your numeric Telegram user ID | `123456789` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `MONGO_DB_URI` | MongoDB connection string | `mongodb+srv://user:pass@cluster.mongodb.net` |
| `DB_NAME` | MongoDB database name | `MikoDB` |
| `EVENT_LOGS` | Channel ID for bot level event logs | `-1001234567890` |
| `MESSAGE_DUMP` | Dump chat ID for archived messages | `-1001234567890` |
| `SUPPORT_CHAT` | Support group username without the `@` | `MySupportGroup` |
| `SUPPORT_ID` | Support group numeric ID | `-1001234567890` |

### Optional

| Variable | Default | Description |
| --- | --- | --- |
| `DEV_USERS` | empty | Space separated sudo user IDs |
| `DRAGONS` | empty | Space separated sudo user IDs |
| `DEMONS` | empty | Users allowed to run the global ban command |
| `WOLVES` | empty | Whitelisted users that cannot be banned |
| `TIGERS` | empty | Users the bot may never ban |
| `BL_CHATS` | empty | Space separated blacklisted chat IDs |
| `LOAD` | empty | Force a plugin start order |
| `NO_LOAD` | empty | Skip plugins by file name |
| `DEL_CMDS` | `True` | Delete command messages from unprivileged users |
| `STRICT_GBAN` | `True` | Enforce global bans in new groups |
| `ALLOW_CHATS` | `True` | Accept private chat usage |
| `ALLOW_EXCL` | `True` | Accept excluded chat usage |
| `INFOPIC` | `True` | Use the image info card instead of a text card |
| `LOGGER` | `True` | Write rotating log files |
| `LOG_LEVEL` | `INFO` | Root log level |
| `ACTIVITY_LOG` | `False` | Log every incoming update summary |
| `BAN_STICKER` | empty | Sticker file ID banned in all groups |
| `GEMINI_API_KEY` | empty | Enables `/askai` and `/palm` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model id |
| `TEMP_DOWNLOAD_DIRECTORY` | `./` | Scratch directory for media |

Never commit a filled `.env`. The file is already listed in `.gitignore`.

---

## Deployment

All three targets run the same entry point: `python -m Mikobot`.

### Heroku

The repository ships [`app.json`](app.json), which declares the worker dyno, the PostgreSQL 16
addon, and every required environment variable with an inline description.

<p align="center">
  <a href="https://dashboard.heroku.com/apps/new?template=https://github.com/bisug/YaeMiko-V2">
    <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy to Heroku" width="220">
  </a>
</p>

[`heroku.yml`](heroku.yml) pins the [Docker](Dockerfile) build so Heroku and local containers behave
identically. [`Procfile`](Procfile) declares `worker: python -m Mikobot` for non Docker builds.

Steps:

1. Create a Telegram application at [my.telegram.org/apps](https://my.telegram.org/apps) for
   `API_ID` and `API_HASH`.
2. Create the bot with [@BotFather](https://t.me/BotFather) for `TOKEN`.
3. Create a free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster for `MONGO_DB_URI`.
4. Press the deploy button, fill the prompted variables, and confirm the dyno.
5. Verify the startup banner lands in the support chat and that `/start` replies.

### Docker

[`Dockerfile`](Dockerfile) is a two stage build: a `builder` stage installs the wheels, and the
runtime stage is `python:3.14.7-slim` with `ffmpeg`, `curl` and `libgomp1` for ONNX Runtime.

```bash
docker build -t yaemiko .
docker run --env-file .env -e ENV=True yaemiko
```

### Local host or VPS

```bash
sudo apt-get update && sudo apt-get upgrade -y          # 1. Update the system
sudo apt-get install -y python3-pip ffmpeg libgomp1     # 2. Install Python, ffmpeg, OpenMP

git clone https://github.com/bisug/YaeMiko-V2.git  # 3. Clone the repository
cd YaeMiko

python3 -m venv .venv && source .venv/bin/activate       # 4. Create a virtual environment
pip install -U pip && pip install -r requirements.txt    # 5. Install dependencies

vi .env                                                 # 6. Add the required keys, see below

python -m Mikobot                                       # 7. Start the bot
```

Keep it running with a process supervisor or tmux:

```bash
sudo apt install -y tmux
tmux new -s yaemiko
python -m Mikobot
# detach with Ctrl+b then d, reattach with tmux attach -t yaemiko
```

---

## Continuous integration

[`ci.yml`](.github/workflows/ci.yml) runs on every push to `main` and every pull request. The
`validate` job, which the `docker` job depends on, executes:

```bash
python -m json.tool app.json >/dev/null      # manifest is valid JSON
python -m compileall -q .                    # every module compiles
python -m unittest discover -s tests -v      # regression suite
git diff --check                             # no whitespace damage
```

The `docker` job then builds the worker image with Buildx.

The regression suite in [`tests/test_regressions.py`](tests/test_regressions.py) is dependency free
and uses AST extraction to assert behaviour, including that every inline button call carries an
explicit style and that the permission related PTB fields are the ones the installed version
supports.

Reproduce the full gate locally:

```bash
python -m json.tool app.json >/dev/null
python -m compileall -q .
python -m unittest discover -s tests -v
git diff --check
```

---

## Security notes

- **Token redaction.** `RedactingFormatter` in [`Mikobot/__init__.py`](Mikobot/__init__.py) rewrites
  anything matching `bot<digits>:<token>` to `bot<redacted>` in every log record.
- **HTTP logger noise.** The `httpx` and `httpcore` loggers are set to `WARNING` because at `INFO`
  they print the complete Telegram API URL, which contains the bot token in the path.
- **Config precedence.** Environment values win over `.env`, and `.env` wins over `variables.py`.
- **Connection hygiene.** The SQL engine uses `pool_pre_ping=True` and `pool_recycle=1800` so idle
  connections dropped by managed platforms are replaced instead of raising at query time.
- **Docker hygiene.** The runtime stage copies only the virtual environment from the builder, and
  apt lists are removed in both stages.
- **Static analysis.** CodeQL runs on push, on pull requests, and weekly.

---

## Contributing

1. [Open an issue](https://github.com/bisug/YaeMiko-V2/issues) describing the behaviour first.
2. Fork the repository and create a branch from `main`.
3. Follow the layout of the module you are editing: a new feature belongs in
   `Mikobot/plugins/<name>.py` and is picked up automatically.
4. Run the CI gate locally before pushing.
5. Open a pull request that explains the change and references the issue.

For new plugins, set `__mod_name__` so the module appears correctly in `/help`, and give every inline
button an explicit `style`.

---

## Credits

### Upstream projects

- [Infamous-Hydra](https://github.com/Infamous-Hydra) for the original architecture and maintenance.
  This repository, [bisug/YaeMiko-V2](https://github.com/bisug/YaeMiko-V2), is the maintained fork
  and the main home of the project.
- [Team ProjectCodeX](https://github.com/Team-ProjectCodeX) for the module framework
- [Paul Son Of Lars](https://github.com/PaulSonOfLars) for the original Telegram bot foundation
- [lostb053](https://github.com/lostb053) for the anime module lineage

### Runtime libraries

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for the Bot API
  application, rate limiter and persistence
- [Kurigram](https://github.com/KurimuzonAkuma/Kurigram) for the MTProto client
- [TgCryptoRust](https://pypi.org/project/TgCryptoRust/) for accelerated encryption
- [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) and
  [psycopg](https://github.com/psycopg/psycopg) for the PostgreSQL layer
- [PyMongo](https://github.com/mongodb/mongo-python-driver) for the MongoDB layer
- [httpx](https://github.com/encode/httpx) for the shared asynchronous HTTP client

### External data sources

- [Openverse](https://openverse.org/) for openly licensed image search
- [Google Gemini API](https://ai.google.dev/gemini-api) for AI chat
- [Hacker News Algolia API](https://hn.algolia.com/api) for technology news search
- [DuckDuckGo Instant Answer API](https://duckduckgo.com/duckduckgo-help-pages/results/duckduckgo-instant-answer-api)
  for quick web answers
- [Wikimedia Commons API](https://commons.wikimedia.org/wiki/Commons:Commons_API) for public media
  and attribution data
- [TheSportsDB](https://www.thesportsdb.com/) for cricket and football schedules
- [PokeAPI](https://pokeapi.co/) for Pokemon reference data

### Services

- [Heroku](https://www.heroku.com/) for worker hosting and the PostgreSQL addon
- [MongoDB Atlas](https://www.mongodb.com/atlas) for the document store
- [GitHub Actions](https://github.com/features/actions),
  [CodeQL](https://github.com/github/codeql) and
  [Dependabot](https://docs.github.com/en/code-security/dependabot) for CI and security

Anyone missing from this list can open a pull request or
[email the maintainers](mailto:makandu2054@gmail.com). The bot name, username and ID are fetched
from Telegram at startup rather than hardcoded.

---

## License

[MIT](LICENSE) with copyright held by Infamous-Hydra and ProjectCodeX. See the
[LICENSE](LICENSE) file for the full text.
