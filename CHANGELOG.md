# Changelog

All notable changes to YaeMiko are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `/tr` no longer raises `UnboundLocalError` for a source language with one dash
  that is not a hyphenated locale in the language table, such as `de-at`.
  `dest_lang` was only assigned inside the loop that looks for such an entry, so
  any other single-dash source reached the read with the name never bound.
- `/tr` no longer raises `UnboundLocalError` when replying to a message that has
  neither text nor a caption, such as a photo or a sticker. The handler now
  answers that there is no text to translate.
- The regression suite no longer contains duplicate class definitions. Five
  byte-identical copies had accumulated, and Python rebinds the name rather than
  complaining, so the earlier copies were never collected: the reported test
  count overstated what the suite actually exercised.

### Changed

- `Mikobot/plugins/tr.py` imports `google_translator` from
  `Mikobot/plugins/anime.py` instead of keeping a near-verbatim second copy of
  the class, and six imports that only the copy used were dropped. The two
  copies had already drifted, so a fix to one did not reach the other.
- The language-fallback and undefined-name guards now check `anime.py`, where
  the translator class is defined, rather than the `tr.py` copy that no longer
  exists.

### Added

- Regression tests covering both `/tr` failures above. Each fails with the
  original `UnboundLocalError` and passes with the fix.
- A suite gate that fails when a class name is defined twice, so a shadowed
  copy cannot come back unnoticed.

### Dependencies

None. Every pin in `requirements.txt` was checked against the PyPI JSON API and
is already the current release, so nothing was bumped.

## [Previous work]

Earlier changes are described in the commit history, the most recent being
`fix: repair ten defects an audit of the port found`.

[Unreleased]: https://github.com/bisug/YaeMiko-V2/compare/main...HEAD