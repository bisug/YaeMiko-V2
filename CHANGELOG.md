# Changelog

All notable changes to YaeMiko are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Integrated `uv` for project package management and reproducible dependency synchronization (`uv.lock`).
- Configured Astral's `ty` static type checker in `pyproject.toml` targeting `Mikobot` and `Database`.
- Added b-tree index `chat_feds_fed_id_idx` on `chat_feds(fed_id)` to optimize federation deletion and filter operations without table scans.
- Support in Quotely for channel quotes, group chat reply chain fetching, delete permission handling, and crisp sticker webp output.
- Extensive regression suites in `tests/test_regressions.py` covering null safety, exception handling, memory bounds, type safety, and database index verification (expanding test suite to 363 tests).
- Regression tests covering both `/tr` failures, the `@can_restrict` owner crash, the duplicated member lookup, the AFK `text_mention` drop, the channel-post reply crash, the pagination divide, and the two upload-response cases.
- A suite gate that fails when a class name is defined twice, so a shadowed copy cannot come back unnoticed.

### Changed

- Upgraded Python runtime pin from 3.14.8 to 3.14.10 across `.python-version`, `Dockerfile`, CI workflows, and documentation.
- Configured multi-stage `Dockerfile` with `UV_PROJECT_ENVIRONMENT=/opt/venv` to install dependencies directly into the isolated virtual environment.
- CI pipeline migrated to `astral-sh/setup-uv` with `uv sync --frozen --no-dev`.
- Standardized all multi-exception `except` tuples across the repository to standard PEP 8 syntax (`except (Exc1, Exc2):`).
- Updated documentation across `README.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/DEPLOYMENT.md`, `docs/PLUGINS.md`, and `docs/SYSTEM-REQUIREMENTS.md` to reflect current dependencies, 62 active plugins, 60 database tables, 5 custom indexes, and aiogram 3.x idioms.
- `Mikobot/utils/can_restrict.py` keeps the wrapped handler's `__name__` and `__doc__` through `functools.wraps`, matching every other decorator here. Its refusal message also closes the code span it opened.
- `Mikobot/plugins/tr.py` imports `google_translator` from `Mikobot/plugins/anime.py` instead of keeping a near-verbatim second copy of the class, dropping redundant imports.
- The language-fallback and undefined-name guards now check `anime.py`, where the translator class is defined, rather than the `tr.py` copy.

### Performance

- Memory bounding in `antiflood`: automatically prunes expired flood time windows and stale deque entries.
- Bounded interactive and temporary memory stores with `TTLCache` in `captcha` (challenge store), `welcome` (waitlist and recent clean messages), and `anime` (interactive pages).
- Expanded admin status cache capacity from 256 to 1024 entries.
- Memory optimization in federation ban tracking: transitioned banned user lookups to sets, loading detailed ban information lazily on-demand.
- Fast-path checks: in-memory `is_gbanned` check in `gban` and message lock matching in `locks` before calling Telegram API or PostgreSQL.
- Query reduction: eliminated redundant database calls in `cust_filters` when blacklist or flood checks are inactive.
- Event loop responsiveness: unblocked async event loop in `warns` by delegating database approval checks to `asyncio.to_thread` with lazy evaluation.

### Fixed

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
