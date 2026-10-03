# MongoDB to PostgreSQL migration

Retire MongoDB Atlas and move the last features onto PostgreSQL, which is
already the primary store.

All seven phases are done and verified. `anime.py`, the consumer the original
version of this plan missed, was migrated last; see that section for what it
turned out to need. There is no MongoDB code left in the running bot.

What remains is operational, not code: run the backfill, exercise each feature
in a real chat, then revoke the Atlas credentials.

## Where the codebase actually stands

Measured, not assumed:

| Signal | Before | After |
| --- | --- | --- |
| Mongo modules | 12 | 0 |
| SQL modules | 28 | 35 |
| Plugins reading Mongo | 13 | 0 |
| Runtime dependency | `pymongo` + Atlas | `psycopg` + PostgreSQL only |

## What was migrated

| Phase | Mongo module | PostgreSQL replacement |
| --- | --- | --- |
| 0 | `users_chats_db.py`, `afk_db.py`, `blacklistdb.py`, `mongodb.py` | deleted; SQL twins already existed |
| 1 | `users_db.py` | `Database/sql/userinfo_sql.py` over `users_sql.Users` |
| 2 | `whispers.py`, `locale_db.py` | `whispers_sql.py`, `locale_sql.py` |
| 3 | `toggle_mongo.py`, `fsub_db.py` | `toggle_sql.py`, `fsub_sql.py` |
| 4 | `karma_mongo.py` | `karma_sql.py`, plus the karma row in `toggle_sql` |
| 5 | `sangmata_db.py` | `sangmata_sql.py` |
| 6 | `anime.py`'s 13 collections, `db.py` | `anime_sql.py`; `Database/mongodb/` deleted |

`scripts/backfill_mongo_to_sql.py` copies the data across. It has not been run
against a real cluster; the runbook below is the procedure.

## Deviations from the original plan

The plan this replaces was written before any of it was implemented and was
wrong in four places. Each was corrected against the source rather than
followed.

**`afk_db.py` was not dead.** The plan called it dead, with "no importer" and
"risk: none". `tests/test_regressions.py` loaded `is_cleanmode_on` out of it.
The test went with the module; cleanmode itself had no caller anywhere in
`Mikobot`, so no behaviour was lost.

**`anime.py` was missing entirely.** It imports `Database.mongodb.db` directly
and holds 13 collections across 60 operations, more than the seven modules the
plan budgeted for. It is the last consumer and the reason Phase 6 cannot start.

**`mongodb.py` was dead, not infrastructure.** The plan listed it as live. It
had no importers, and it called `exiter(1)` on a connection error, so it was a
startup landmine rather than infrastructure.

**Three schemas were wrong.** The plan's `fsub_settings` needed an
approved-user list that `fsub_db.py` never had. Its karma table was keyed on
`user_id` with an integer score, but karma is keyed on
`(chat_id, alpha-encoded name)` holding a `{"karma": n}` value. Its sangmata
JSONB column was for arbitrary key/value data, but that collection only ever
held `username`, `first_name` and `last_name`. Real columns and the real keys
are used instead.

## The toggle trap

The toggles did not agree on what a missing row meant, and getting this wrong
silently inverts a feature for every chat.

| Toggle | Mongo row present means | Default with no row |
| --- | --- | --- |
| `welcome` | turned OFF | ON |
| `nekomode` | turned OFF | ON |
| `karma` | turned OFF | ON |
| `sangmata` | turned ON | OFF |
| `nsfw` | turned ON | OFF |

One `chat_toggles` table with a `(chat_id, feature)` primary key covers all of
them, but the default has to be per-feature, so it lives in `DEFAULTS` in
`toggle_sql.py` rather than in the schema.
`scripts/backfill_mongo_to_sql.py` records the same polarity in
`TOGGLE_SOURCES`; the two must be kept in step.

## Phase 6: anime.py

`anime.py` was the last Mongo consumer, and not a like-for-like port:

| Collection | Ops | Shape |
| --- | --- | --- |
| `DC` | 12 | disabled commands per group |
| `SFW_GRPS` | 11 | per-group feature flags |
| `GUI` | 9 | group UI text |
| `AUTH_USERS` | 7 | `{id, token}` for the Jikan API |
| `AG`, `CG`, `SG` | 4 each | airing group settings |
| `IGNORE` | 3 | ignored users |
| `GROUPS`, `CC` | 2 each | group and channel records |
| `HD`, `MHD` | 1 each | headline caches |
| `PIC_DB` | 0 | declared, never used |

Most of these are per-chat flags or single values, so one
`anime_group_settings` table keyed on `(collection, chat_id, key)` carries them
all, with `anime_tokens` for `AUTH_USERS`. Carrying the collection name in the
key also removes the polymorphism: in Mongo a `DC` document and a toggle
document were told apart only by which field was present.

Four things did not survive a mechanical port:

**`DC` needed no table.** `disable_sql.py` already held the disabled commands
in PostgreSQL and was what `/disable` had always written. anime.py was reading
a Mongo mirror that nothing had written since the SQL layer landed, so those
twelve reads were permanently stale. They now read `disabled_commands`, which
makes them correct rather than merely ported.

**`CC` needed an integer column.** The owning user id was compared against an
int, so a text column would have silently failed every authorisation check.

**`unpin` needed an integer column.** auto_unpin reads it back with
`type(unpin) is int` to choose its label, so a text column would have shown
"OFF" for every setting.

**`GUI` mixed key types.** It was read with `str(id_)` and written with an int
`gid`, which are different documents in Mongo. Normalising to `str` on both
sides makes the read find what the write stored.

`PIC_DB` was declared and never used, and `HD`/`MHD` carry `pin`, `unpin` and
`next_unpin` alongside their membership row, so all of those are real keys on
the one table.

With that done, `Database/mongodb/` was deleted and these went with it:

- `Database/mongodb/db.py`
- `pymongo` from `requirements.txt`
- `close_db()` from the `Mikobot/__main__.py` shutdown block
- `MONGO_DB_URI` and `DB_NAME` from `Mikobot/__init__.py`, `app.json`,
  `render.yaml` and `docs/CONFIGURATION.md`

The completion check now passes:

```
grep -rn "mongodb\|pymongo\|MONGO_DB_URI" Mikobot Database requirements.txt
```

returns nothing, and the bot boots with no `MONGO_DB_URI` set.

## Conventions the new modules follow

**Column types are not uniform.** `chat_id` is `String(14)` in most tables,
`user_id` is `BigInteger`. Match the neighbouring table.

**`chat_id` must be cast.** Mongo stored it as an integer. Every backfill
writes `str(...)`. Skipping the cast produces a table that looks populated and
matches nothing.

**Every data helper is wrapped** in `@unit_of_work_guard` and closes its
session in a `finally`. `tests/test_regressions.py` enforces this, private
helpers included, so an unwrapped `_read` fails the suite.

**Tables are created explicitly** with
`Model.__table__.create(bind=ENGINE, checkfirst=True)`.

**The SQL layer is synchronous.** The plugins that read the Mongo modules were
`await`ing them and those `await`s were dropped. The surrounding code in
`feds.py` and `gban.py` already called the sync SQL helpers directly, so this
matches the local convention rather than adding a second one.

## Verification

`python -m compileall -q .`, `python tests/validate_docs.py` and
`python tests/validate_deployment.py` all pass.

The suite does not pass on a machine that is not the pinned runtime, and it did
not pass before this work either. `.python-version` pins 3.14.7; on 3.12 with
`aiogram` absent it reports 49 failures and 67 errors, nearly all from
`RemovedStdlibApiTests` asserting that 3.14-removed APIs are gone. The count
was compared against a pristine `git worktree` of `HEAD` before and after, and
is unchanged: **zero regressions**. Run it on 3.14.7 with the requirements
installed for a meaningful result.

Each new module was also exercised directly against a real SQL database for
its behaviour rather than its syntax: the toggle defaults and per-feature
polarity, the `{}` that `get_db_lang` owes `localization.py`, the int-to-str
`chat_id` cast, and `int_to_alpha`/`alpha_to_int` against the original
implementation over 305 ids.

## Runbook

The code is done. These four steps are not, and they are the only things left.
Do them in order.

### 1. Snapshot MongoDB first

Atlas gives you a free M0 snapshot, or use `mongodump`. This is the only
rollback path once the Mongo modules are deleted:

```
mongodump --uri "$MONGO_DB_URI" --out ./mongo-backup-$(date +%F)
```

### 2. Run the backfill with the bot stopped

The SQL modules create their tables with `checkfirst=True`, which creates a
missing table but never alters an existing one. Two column types were corrected
after the schema was first written, so an already-migrated database needs these
by hand. Both are widenings, so neither rewrites or loses data:

```sql
ALTER TABLE whispers ALTER COLUMN id TYPE VARCHAR(32);
ALTER TABLE couple  ALTER COLUMN c1_id TYPE BIGINT;
ALTER TABLE couple  ALTER COLUMN c2_id TYPE BIGINT;
```

`whispers.id` was `VARCHAR(20)` against a 32-character `uuid4().hex`, so every
whisper insert failed with `value too long for type character varying(20)`.
`couple.c1_id` and `c2_id` were 32-bit `INTEGER` while every other user-id
column in the codebase is `BIGINT`; Telegram ids passed 2**31 in 2021.

Skip this if the database was created by the current code. Confirm with
`\d whispers` and `\d couple` if you are unsure.

Then run the backfill:

```
python scripts/backfill_mongo_to_sql.py --dry-run
```

Prints a per-collection count and touches nothing. It needs `MONGO_DB_URI` but
not `DATABASE_URL`, so you can check what it *would* copy before pointing it at
PostgreSQL. Compare those counts against what Atlas reports; a large shortfall
means a collection name changed.

Then, for real:

```
python scripts/backfill_mongo_to_sql.py
```

One transaction, so a failure writes nothing. `DATABASE_URL` must be set. The
new tables are created on import if they do not exist.

**Ordering matters.** The call sites now read the new tables, so the backfill
has to happen before you start the bot. Anything written to Mongo after this
point is not carried over, which is why the bot stays down.

### 3. Start the bot and exercise each feature by hand

The suite does not cover these paths, and a table that looks right can still
be read wrong. Check in a real group:

| Feature | What to confirm |
| --- | --- |
| Ban buttons | Name shows, not `user(123)` |
| `/karma`, couple | Counts survive; `alpha_to_int` round-trips |
| Whisper | Send one, open it, confirm it is not a 500. This is the row that catches the `VARCHAR(20)` bug above |
| Locale | `/setlang`, then a message in that language |
| Welcome / nsfw / nekomode | Toggle off, confirm it stays off |
| Force-subscribe | `/fsub on`, confirm a non-member is muted |
| Sangmata | Toggle, then a name change is reported |
| Anime settings | NSFW/airing/crunchy/subsplease toggles, UI bullet and case, Auto Pin, Auto Unpin |
| `/disable` | Disable an anime command, confirm anime.py honours it |

That last row matters most: `anime.py` used to read a Mongo mirror of the
disabled commands that nothing wrote, so it may behave differently now. That is
the intended fix, not a regression.

### 4. Revoke the Atlas credentials

Deleting `MONGO_DB_URI` from `.env` does not invalidate a leaked SRV string.
Drop the database user in Atlas, or delete the cluster. Only after step 3
passes, because the snapshot in step 1 is your only way back.

Then drop the `MONGO_DB_URI` and `DB_NAME` rows from any `.env`, CI secret or
hosting dashboard still holding them. They are no longer read by anything.

### If something goes wrong

Restore the Mongo snapshot, `git revert` the migration commit, and redeploy.
Each phase kept its Mongo module for a release for exactly this reason, so
reverting gives you a bot that reads the data you already have.

## Rollback

Every Mongo module is deleted, so rollback is `git revert` plus restoring the
snapshot from step 1 of the runbook. Take that snapshot before the backfill and
keep it until the features have run in a real chat.

## What this does not cover

Redis, and any move to asynchronous SQL. Both were considered and are separate
work with separate justifications. Redis buys little while the hot path is
already served from in-process dicts and the bot runs as a single worker; it
becomes necessary the moment a second worker exists, and at that point it is a
correctness requirement rather than a performance one.
