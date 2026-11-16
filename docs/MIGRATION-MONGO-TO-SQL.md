# MongoDB to PostgreSQL migration

MongoDB was retired. PostgreSQL is the only store; no MongoDB code or dependency remains in the
running bot.

## What changed

| Phase | Replacement |
| --- | --- |
| 0 | Deleted `users_chats_db.py`, `afk_db.py`, `blacklistdb.py` and `mongodb.py`; SQL twins already existed |
| 1 | `users_db.py` replaced by `Database/sql/userinfo_sql.py` |
| 2 | `whispers.py` and `locale_db.py` replaced by `whispers_sql.py` and `locale_sql.py` |
| 3 | `toggle_mongo.py` and `fsub_db.py` replaced by `toggle_sql.py` and `fsub_sql.py` |
| 4 | `karma_mongo.py` replaced by `karma_sql.py` and the karma row in `toggle_sql.py` |
| 5 | `sangmata_db.py` replaced by `sangmata_sql.py` |
| 6 | `anime.py`'s collections replaced by `anime_sql.py`; `Database/mongodb/` deleted |

`pymongo`, `MONGO_DB_URI` and `DB_NAME` were removed from the code and deployment manifests.
`scripts/db_cleanup.sql` lists the legacy tables and columns that no model declares; nothing runs
it automatically.

The one store is now `Database/sql/`; see [DATABASE.md](DATABASE.md).

## Conventions the SQL modules follow

- `chat_id` is a `String` column; legacy values were cast from Mongo integers with `str(...)`.
- User ids are `BIGINT`; chat keys use `String`.
- Every data helper is wrapped in `@unit_of_work_guard` (enforced by `tests/test_database.py`).
- Tables are created by `create_all_tables()` in `Database/sql/__init__.py`.

## Open item

The original plan referred to `scripts/backfill_mongo_to_sql.py` to copy data from a Mongo cluster.
That script is not in this repository. If you are migrating data from an older Mongo-backed
instance, the backfill procedure has to be written or recovered before the old credentials are
revoked.

## Verification

`python -m compileall -q .` and `pytest -v` pass on the pinned Python version with the pinned
dependencies installed.
