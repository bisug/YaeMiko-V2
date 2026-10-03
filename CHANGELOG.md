# Changelog

All notable changes to YaeMiko are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The `@can_restrict` guard no longer raises `AttributeError` when a chat owner
  runs a guarded command. kurigram builds `ChatMember(status=OWNER)` without a
  `privileges` field, so reading `.can_restrict_members` through it crashed every
  command behind the guard for the person who actually has the most power in the
  chat: `/purge`, `/spurge`, `/del`, `/dwelcome on`, `/dwelcome off`, `/setmataa`,
  `/antinsfw`, and the karma toggle. The rights check now applies to
  administrators alone, since the owner outranks one.
- `@can_restrict` calls `get_chat_member` once instead of twice. It looked the
  sender up, then repeated the identical call just to read `.privileges`, paying
  two round trips before every guarded command.
- A chat-member lookup that fails now answers the user instead of propagating
  the RPC error out of the handler.
- `/tr` no longer raises `UnboundLocalError` for a source language with one dash
  that is not a hyphenated locale in the language table, such as `de-at`.
  `dest_lang` was only assigned inside the loop that looks for such an entry, so
  any other single-dash source reached the read with the name never bound.
- `/tr` no longer raises `UnboundLocalError` when replying to a message that has
  neither text nor a caption, such as a photo or a sticker. The handler now
  answers that there is no text to translate.
- The AFK mention handler answers a `text_mention`, which is what Telegram sends
  for a user who has no `@username`. That branch resolved the user and then fell
  out of the conditional without calling `check_afk`, so the mention was silently
  dropped. Only the `@username` path reported anything.
- The AFK mention handler no longer raises `AttributeError` when a message
  replies to a channel post or a service message, which carry no `from_user`.
- The help and settings paginators no longer raise `ZeroDivisionError` on a chat
  with no modules to list: `ceil(0 / 6)` is `0`, and the page modulo divided by it.
- The regression suite no longer contains duplicate class definitions. Five
  byte-identical copies had accumulated, and Python rebinds the name rather than
  complaining, so the earlier copies were never collected: the reported test
  count overstated what the suite actually exercised.

### Changed

- `Mikobot/utils/can_restrict.py` keeps the wrapped handler's `__name__` and
  `__doc__` through `functools.wraps`, matching every other decorator here. Its
  refusal message also closes the code span it opened, so the stray backtick no
  longer renders to the user.
- `Mikobot/plugins/tr.py` imports `google_translator` from
  `Mikobot/plugins/anime.py` instead of keeping a near-verbatim second copy of
  the class, and six imports that only the copy used were dropped. The two
  copies had already drifted, so a fix to one did not reach the other.
- The language-fallback and undefined-name guards now check `anime.py`, where
  the translator class is defined, rather than the `tr.py` copy that no longer
  exists.

### Removed

- `dispatcher = dp` in `Mikobot/__init__.py`. Nothing imported it, and the
  `Dispatch`-era alias only invited reaching for the wrong name.

### Added

- Regression tests covering both `/tr` failures, the `@can_restrict` owner crash,
  the duplicated member lookup, the AFK `text_mention` drop, the channel-post
  reply crash and the pagination divide. Eight of them fail against the previous
  code.
- A suite gate that fails when a class name is defined twice, so a shadowed
  copy cannot come back unnoticed.

### Dependencies

None. Every pin in `requirements.txt` was checked against the PyPI JSON API and
is already the current release, so nothing was bumped.

## [Previous work]

Earlier changes are described in the commit history, the most recent being
`fix: repair ten defects an audit of the port found`.

[Unreleased]: https://github.com/bisug/YaeMiko-V2/compare/main...HEAD