# Changelog

All notable changes to YaeMiko are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Kurigram 2.2.27 & kuricrypt integration** — migrated fast cryptography backend from `tgcrypto-c` to
  `kuricrypt==0.1.1` (Rust/PyO3) and updated Kurigram to `2.2.27`.
- **Python 3.14.10 pin** — `.python-version`, `pyproject.toml` (`requires-python = ">=3.14"`),
  `Dockerfile` (`python:3.14.10-slim`), and CI workflow (`python-version: "3.14.10"`).
- **Native lazy imports** (`sys.set_lazy_imports('all')`) enabled in `Mikobot/__init__.py` and
  `Mikobot/__main__.py`, with a filter that excludes `sqlalchemy.*` and `Database.sql.*` to keep
  SQLAlchemy ORM class-body execution correct. Reduces cold-start import time to near zero for all
  third-party modules.
- `SESSION = None` guard in `Database/sql/__init__.py` when `unittest` is in `sys.modules`, plus
  early-return guards in all `__load_*` and `_ensure_*` functions across every SQL module so the
  test suite runs without a real database connection.
- `antinsfw.py` now catches `ImportError` from `opennsfw_onnx` and raises a clear `RuntimeError`
  when running on Python 3.15+ where the ONNX wheels are not available.
- Integrated `uv` for project package management and reproducible dependency synchronization (`uv.lock`).
- Configured Astral's `ty` static type checker in `pyproject.toml` targeting `Mikobot` and `Database`.
- Added b-tree index `chat_feds_fed_id_idx` on `chat_feds(fed_id)` to optimize federation deletion and filter operations without table scans.
- Support in Quotely for channel quotes, group chat reply chain fetching, delete permission handling, and crisp sticker webp output.
- Extensive regression suites in `tests/test_regressions.py` covering null safety, exception handling, memory bounds, type safety, and database index verification (expanding test suite to 363 tests).
- Regression tests covering both `/tr` failures, the `@can_restrict` owner crash, the duplicated member lookup, the AFK `text_mention` drop, the channel-post reply crash, the pagination divide, and the two upload-response cases.
- A suite gate that fails when a class name is defined twice, so a shadowed copy cannot come back unnoticed.

### Changed

- **The database layer was cleaned up.** The schema, the migrations and the queries were audited
  against the live database, and the following changed:
  - Nine indexes added: `warns_chat_id_idx`, `connection_history_chat_id_idx`,
    `feds_subs_sub_idx`, and the unique indexes `welcome_urls_uc`, `leave_urls_uc`,
    `note_urls_uc`, `cust_filter_urls_uc`, `feds_name_uc`, `feds_owner_uc`. The unique ones hold
    a uniqueness the code assumed and the schema did not state, so a duplicate silently hid a
    federation or a button.
  - `ensure_index()` takes a `unique` flag, and `create_pending_indexes()` replays the list after
    `create_all` has made the tables. The modules ask for their indexes while they are imported,
    which is before the tables exist, so a fresh database used to get its indexes on the second
    start.
  - `couple.c1_id` and `couple.c2_id` are widened to `BIGINT`. The table was created with an
    integer column, which caps a Telegram user id at 2\*\*31-1.
  - `cust_filters` gained the missing column migration, so a deployment whose table predates
    `reply_text`, `file_type` and `file_id` keeps the old shape no longer, and the legacy
    `has_markdown` column is dropped because the model no longer declares it.
  - Dead columns removed from the models: `notes.is_reply`, `notes.has_buttons`,
    `cust_filters.has_markdown`, `antiflood.count`, `antiflood.user_id` and `raid_chats.notified`.
    Nothing wrote them and nothing read them.
  - `raid_mode.time` and `raid_mode.acttime` are `BIGINT`, like the raid columns they sit next to.
  - `scripts/db_cleanup.sql` holds the tables from the MongoDB era that no model declares and the
    columns that no model declares any more. Nothing in it runs by itself.
- **Python runtime pinned to 3.14.10** across `.python-version`, `pyproject.toml`
  (`requires-python = ">=3.14"`, ruff `target-version = "py314"`), `Dockerfile`, CI workflows, and all
  documentation. Previous pin was 3.15.2.
- `onnxruntime` and `opennsfw-onnx` keep the `python_version < "3.15"` marker, so on the pinned 3.14 the
  anti-NSFW wheels install and the check works out of the box.
- `onnxruntime` and `opennsfw-onnx` now conditioned on `python_version < "3.15"` in both
  `pyproject.toml` and `requirements.txt` (no cp315 wheels available yet). The NSFW check in
  `antinsfw.py` raises a clear `RuntimeError` on Python 3.15+.
- Upgraded Python runtime pin from 3.14.8 to 3.14.10 across `.python-version`, `Dockerfile`, CI workflows, and documentation.
- Configured multi-stage `Dockerfile` with `UV_PROJECT_ENVIRONMENT=/opt/venv` to install dependencies directly into the isolated virtual environment.
- CI pipeline migrated to `astral-sh/setup-uv` with `uv sync --frozen --no-dev`.
- Standardized all multi-exception `except` tuples across the repository to standard PEP 8 syntax (`except (Exc1, Exc2):`).
- Updated documentation across `README.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/DEPLOYMENT.md`, `docs/PLUGINS.md`, and `docs/SYSTEM-REQUIREMENTS.md` to reflect current dependencies, 62 active plugins, 60 database tables, 5 custom indexes, and aiogram 3.x idioms.
- `Mikobot/utils/can_restrict.py` keeps the wrapped handler's `__name__` and `__doc__` through `functools.wraps`, matching every other decorator here. Its refusal message also closes the code span it opened.
- `Mikobot/plugins/tr.py` imports `google_translator` from `Mikobot/plugins/anime.py` instead of keeping a near-verbatim second copy of the class, dropping redundant imports.
- The language-fallback and undefined-name guards now check `anime.py`, where the translator class is defined, rather than the `tr.py` copy.
- `Mikobot/utils/can_restrict.py` gained a shared `has_restrict_rights(member)` helper, and `unbanall`,
  `zombies` and `fsub` now use it instead of each reading `.privileges` on its own.
- `Mikobot/plugins/topics.py` reads the forum layout from the Kurigram chat, which is the layer that
  carries `has_forum_sidebar`; the Bot API exposes no such flag.
- `Mikobot/plugins/alive.py` reports the crypto backend by probing for `kuricrypt` and `tgcrypto`
  rather than reading Kurigram's private `_crypto_backend` attribute.
- `Mikobot/plugins/quotely.py` derives an unmapped entity type from the enum member name and forwards
  the `unix_time` and `date_time_format` fields of a `date_time` entity.
- `Mikobot/plugins/couple.py` resolves both couple members in one batched `get_users` call and
  reports the unresolvable case instead of raising on a missing member.
- Ruff is now configured in `pyproject.toml` and runs in CI. The rule set covers the defects worth
  catching here (unused names, undefined names, unsorted imports, bugbear and simplification
  rules) and leaves the house style alone: lazy `%s` logging and the deliberate broad `except`
  that logs and continues are not flagged.
- The repository is formatted with `ruff format`, and the unused imports, unused locals and dead
  code the linter found were removed across the plugins and the data layer.

### Performance

- Memory bounding in `antiflood`: automatically prunes expired flood time windows and stale deque entries.
- Bounded interactive and temporary memory stores with `TTLCache` in `captcha` (challenge store), `welcome` (waitlist and recent clean messages), and `anime` (interactive pages).
- Expanded admin status cache capacity from 256 to 1024 entries.
- Memory optimization in federation ban tracking: transitioned banned user lookups to sets, loading detailed ban information lazily on-demand.
- Fast-path checks: in-memory `is_gbanned` check in `gban` and message lock matching in `locks` before calling Telegram API or PostgreSQL.
- Query reduction: eliminated redundant database calls in `cust_filters` when blacklist or flood checks are inactive.
- Event loop responsiveness: unblocked async event loop in `warns` by delegating database approval checks to `asyncio.to_thread` with lazy evaluation.

### Fixed

- The lock allowlist helpers raised `TypeError` on every call. `Select.where()` takes its criteria
  positionally, and `rmallow_all`, `list_allowed` and `allowed_for` passed the column as a keyword
  argument. `allowed_for` is on the per message path, so the allowlist never worked.
- The clean welcome switch and the id of the last welcome message shared the column
  `welcome_pref.clean_welcome`. The switch was stored as 1, and the reader took a stored 1 for a
  message id and asked the bot to delete message 1 of the chat. The switch is
  `welcome_pref.clean_welcome_enabled` now, and the migration reads the old column: a row that
  holds a message id is a chat that had the switch on.
- The welcome mute mode was written as a Python False into a text column, which PostgreSQL
  refuses, so the command that turned the mute off failed. The mode is `off`, `soft` or `strong`.
- A filter saved in the newer format raised `AttributeError` when it was sent: the plugin read
  `has_media_spoiler` off the row and the model never declared it.
- A filter saved in the newer format was recognised by a placeholder string in the reply column, so
  a user who typed that exact text got the newer format instead of their own. The text is stored in
  both columns now and the newer format is recognised by `reply_text`.
- `anime_group_settings` lost the number of a key when a value was written for it, and the value
  when a number was written. Each setter writes its own column now.
- `bans_feds.first_name` and `gbans.name` are NOT NULL, and Telegram sends no name for a user that
  never set one, so the insert failed. Both fall back to a value now.
- A malformed welcome or goodbye button tuple took the whole save down, because the name and the
  url are NOT NULL. A button without a name or a url is skipped now.
- `except ValueError, SyntaxError, KeyError, TypeError:` in `feds_sql.py` is Python 3.14 syntax
  and breaks on every earlier Python 3.
- The `cust_filters` plugin imports `Types` from `msg_types` itself now. It read
  `sql.Types.TEXT.value` through the database module, which never exposed `Types`, so the plugin
  raised `AttributeError` while importing and the bot died on startup with the database connected.
- `unit_of_work_guard` no longer raises `AttributeError` when there is no session. The guard ran
  before the helper body, so the `if SESSION is None` guard inside a helper never got a chance to
  answer, and a module level call such as `welcome_sql._ResetRaidOnRestart()` took the import of the
  whole module down. A failed import also left the module out of `sys.modules`, so the next import
  defined its tables a second time and raised `Table 'welcome_pref' is already defined`.
- New test imports every plugin module, so an import time error like the two above fails the build
  instead of the dyno.
- A database that cannot be reached now produces one error line and a clean exit instead of four
  tracebacks. The `unittest` check that decided "test mode" matched on a production dyno, because
  importing the bot pulls `unittest` in through a third party package, so the bot kept running with
  a dead database and later died inside a plugin import. The test check is now pytest based, the
  engine is cleared when the connection fails, and the schema migrations that run at import time
  (`raid_sql`, `log_channel_sql`, `blacklist_sql`, `antiflood_sql`, `welcome_sql`) skip a database
  that is unreachable rather than raising out of the import.
- Guarded `message.from_user` and `reply_to_message.from_user` against `None` across plugins (`antinsfw`, `bug`, `karma`, `pkang`, `unbanall`, `users`, `zombies`, `extraction`, `info`, `warns`, `notes`, `stickers`, `admin`, `ban`, `locks`, `gate`, `echo`, `anime`, `feds`) preventing crashes on channel posts or anonymous messages.
- Fixed Quotely regex argument parsing, non-existent entity attribute crash (`EXPANDABLE_BLOCKQUOTE`), missing message entities (italic, bold, code, pre, etc.), and missing group chat reply context.
- Fixed Quotely sticker output and permission checks when attempting to delete replied-to messages.
- Restored missing `Types` import in `Database/sql/cust_filters_sql.py` required by `ENUM_FUNC_MAP`.
- Hardened `ensure_index()` with safe exception handling when importing during offline or database-unavailable contexts.
- Replaced manual temporary file creation in `info` and `stickers` with `tempfile.TemporaryDirectory` and `FSInputFile` to prevent leftover file leaks.
- Fixed anonymous admin permission check in `gate.py` to allow callback challenge flows.
- Specified `postgres` user explicitly in CI's `pg_isready` healthcheck command.
- `/approved`, `/approve` and `/disapprove` read `member.user['first_name']`. `User` is a pydantic model, not a mapping, so the subscript raised `TypeError` and all three answered nothing. They now read the attribute and escape it for the parse mode they actually send with.
- `/approved` batch-fetches chat members with the session rate limiter pacing the batch, skipping failed lookups rather than dropping the whole list.
- Catbox and Litterbox uploads returning a usable link are no longer treated as failures when the host returns unexpected HTTP 500 status codes.
- Upload failure error reporting now includes the response body diagnostics from Catbox.
- The `@can_restrict` guard no longer raises `AttributeError` when a chat owner runs a guarded command, and reduces redundant `get_chat_member` round trips from two to one.
- A chat-member lookup that fails now answers the user instead of propagating the RPC error out of the handler.
- `/tr` no longer raises `UnboundLocalError` for single-dash source languages or messages without text or caption.
- The AFK mention handler answers `text_mention` entities correctly and guards against reply messages with no `from_user`.
- Help and settings paginators no longer raise `ZeroDivisionError` on a chat with no modules to list.
- `unbanall`, `zombies` and `fsub` treat a chat owner as authorized again. Kurigram leaves
  `ChatMember.privileges` unset for an owner, so the rights check denied the owner and reported a
  missing permission on a command the owner may run.
- The forum topic commands accept a chat whose topics live in a sidebar. The flag exists only on the
  Kurigram chat, so the check reads it there instead of asking the Bot API for a field it never sends.
- Quotely no longer sends an entity type of `"<class 'pyrogram.raw.types....'>"` for an entity the
  quote API does not know; the type comes from the enum member name.
- The couple plugin no longer raises `AttributeError` when one of the two members cannot be resolved.
- `/wallpaper` no longer lets a failed send escape the handler as a traceback.
- The Catbox upload fallback no longer raises `NameError`. The reason for the failed Catbox upload was
  read after its `except` block had ended, and Python unbinds the exception name there, so the
  fallback note could not be built.
- The `except TelegramAPIError` clause that followed a broader `except TelegramAPIError` was
  unreachable in `gban` and duplicated in `connection`; both are gone.
- Configuration errors raised while reading the environment now chain the underlying `ValueError`
  with `from None`, so the operator sees the intended message rather than the raw conversion error.

### Removed

- Removed dead and unused 2,361-line `Database/sql/fontsql.py` module.
- Cleaned unused variables, dead imports, and unneeded coroutine awaits across plugins.
- Removed legacy `pip` and manual `venv` references across project workflows in favor of `uv`.
- `dispatcher = dp` in `Mikobot/__init__.py`.

### Dependencies

- Bumped `SQLAlchemy` from 2.1.3 to 2.1.6.
- Bumped `cachetools` from 7.2.0 to 7.2.7.
- Bumped `pillow` from 12.3.0 to 13.0.0.
- Bumped `pyrate-limiter` from 4.5.0 to 4.5.1.
- Bumped `onnxruntime` from 1.30.0 to 1.31.1.

## [Previous work]

Earlier changes are described in the commit history, the most recent being
`fix: repair ten defects an audit of the port found`.

[Unreleased]: https://github.com/bisug/YaeMiko-V2/compare/main...HEAD
