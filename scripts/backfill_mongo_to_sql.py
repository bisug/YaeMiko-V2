"""Backfill the migrated features from MongoDB into PostgreSQL.

One-shot tooling, not part of the running bot: it reads the Atlas collections
and writes the PostgreSQL tables that replaced them. Delete it once every
feature has been verified in a real chat.

Run it with the bot stopped. chat_id is cast to str on every write because
Mongo stored it as an integer and the PostgreSQL tables use String(14); a
missing cast produces a table that looks populated and matches nothing.

    python scripts/backfill_mongo_to_sql.py --dry-run   # report, write nothing
    python scripts/backfill_mongo_to_sql.py             # write, in one txn

The backfill must finish before the call sites are swapped. Writes that land
in Mongo after this runs are not carried over, so keep the bot down for the
window between the two.
"""

import argparse
import os
import sys

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The model classes are imported lazily by load_models(). Importing them here
# would connect to PostgreSQL, which imports Mikobot, which imports aiogram and
# builds the whole bot -- none of which `--help` or `--dry-run` needs.

# Mongo collection -> (feature id, mongo field, polarity of the stored row).
# The toggles disagree: dwelcome/nekomode/karma stored a row to mean OFF, while
# nsfw stored a row to mean ON. is_on below is the truth for each.
TOGGLE_SOURCES = (
    ("dwelcome", "chat_id_toggle", "welcome", False),
    ("nekomode", "chat_id_toggle", "nekomode", False),
    ("nsfw", "chat_id", "nsfw", True),
    ("sangmata", "chat_id_toggle", "sangmata", True),
)


class NullSession:
    """Counts what would be written, for --dry-run.

    The backfill functions call session.merge() unconditionally, so a dry run
    needs an object that answers those calls instead of a None that crashes on
    the first collection.
    """

    def __init__(self):
        self.would_write = 0

    def merge(self, instance):
        self.would_write += 1
        return instance

    def add(self, instance):
        self.would_write += 1
        return instance

    def commit(self):
        pass


def mongo_db():
    uri = os.environ.get("MONGO_DB_URI")
    if not uri:
        sys.exit("MONGO_DB_URI is not set")
    return MongoClient(uri)[os.environ.get("DB_NAME", "MikoDB")]


def load_models():
    """Import the SQL models, connecting to PostgreSQL as a side effect."""
    global AnimeGroupSetting, AnimeToken, ChatLocale, ChatToggle, Couple, Karma
    global SangmataUser, Whisper
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from Database.sql.anime_sql import AnimeGroupSetting, AnimeToken
    from Database.sql.karma_sql import Couple, Karma
    from Database.sql.locale_sql import ChatLocale
    from Database.sql.sangmata_sql import SangmataUser
    from Database.sql.toggle_sql import ChatToggle
    from Database.sql.whispers_sql import Whisper

    uri = os.environ.get("DATABASE_URL")
    if not uri:
        sys.exit("DATABASE_URL is not set")
    uri = uri.replace("postgres://", "postgresql+psycopg://", 1)
    return sessionmaker(bind=create_engine(uri))()


def backfill_whispers(mongo, session, report):
    count = 0
    for doc in mongo["whisper"].find({}):
        session.merge(
            Whisper(doc["WhisperId"], doc["whisperData"]),
        )
        count += 1
    report("whispers", count)


def backfill_locale(mongo, session, report):
    count = 0
    for doc in mongo["locale"].find({}):
        if "chat_id" not in doc or "lang" not in doc:
            continue
        session.merge(ChatLocale(chat_id=str(doc["chat_id"]), lang=doc["lang"]))
        count += 1
    report("chat_locale", count)


def backfill_toggles(mongo, session, report):
    for collection, field, feature, row_means_on in TOGGLE_SOURCES:
        count = 0
        for doc in mongo[collection].find({field: {"$exists": True}}):
            enabled = bool(doc[field]) if row_means_on else False
            session.merge(ChatToggle(str(doc[field]), feature, enabled))
            count += 1
        report(f"chat_toggles[{feature}]", count)


def backfill_karma(mongo, session, report):
    count = 0
    for doc in mongo["karma"].find({"chat_id": {"$exists": True}}):
        chat_id = str(doc["chat_id"])
        for name, entry in (doc.get("karma") or {}).items():
            session.merge(Karma(chat_id, name, entry.get("karma", 0)))
            count += 1
    report("karma", count)

    couples = 0
    for doc in mongo["couple"].find({}):
        chat_id = str(doc["chat_id"])
        for date, pair in (doc.get("couple") or {}).items():
            session.merge(
                Couple(chat_id, date, pair.get("c1_id"), pair.get("c2_id")),
            )
            couples += 1
    report("couple", couples)


def backfill_sangmata(mongo, session, report):
    count = 0
    for doc in mongo["sangmata"].find({"user_id": {"$exists": True}}):
        session.merge(
            SangmataUser(
                doc["user_id"],
                doc.get("username"),
                doc.get("first_name"),
                doc.get("last_name"),
            ),
        )
        count += 1
    report("sangmata_users", count)


def backfill_anime(mongo, session, report):
    """Port the thirteen anime collections.

    SFW_GRPS/AG/CG/SG/HD/MHD were membership rows and GROUPS/IGNORE/CC/GUI held
    one or two values, so they all land in anime_group_settings keyed by
    collection. AUTH_USERS becomes anime_tokens.
    """
    membership = {
        "SFW_GROUPS": "SFW_GRPS",
        "AIRING_GROUPS": "AG",
        "CRUNCHY_GROUPS": "CG",
        "SUBSPLEASE_GROUPS": "SG",
        "HEADLINES_GROUPS": "HD",
        "MAL_HEADLINES_GROUPS": "MHD",
    }
    for collection, name in membership.items():
        count = 0
        for doc in mongo[collection].find({}):
            chat_id = doc.get("id", doc.get("_id"))
            if chat_id is None:
                continue
            session.merge(AnimeGroupSetting(name, str(chat_id), "on", "1"))
            count += 1
        report(f"anime[{name}]", count)

    for collection, name, fields in (
        ("GROUPS", "GROUPS", ("grp",)),
        ("HEADLINES_GROUPS", "HD", ("pin", "unpin", "next_unpin")),
        ("MAL_HEADLINES_GROUPS", "MHD", ("pin", "unpin", "next_unpin")),
    ):
        count = 0
        for doc in mongo[collection].find({}):
            chat_id = doc.get("_id", doc.get("id"))
            if chat_id is None:
                continue
            for field in fields:
                if field in doc:
                    session.merge(
                        AnimeGroupSetting(name, str(chat_id), field, doc[field])
                    )
                    count += 1
        report(f"anime[{name} values]", count)

    ignored = 0
    for doc in mongo["IGNORED_USERS"].find({}):
        session.merge(AnimeGroupSetting("IGNORE", str(doc["_id"]), "on", "1"))
        ignored += 1
    report("anime[IGNORE]", ignored)

    channels = 0
    for doc in mongo["CONNECTED_CHANNELS"].find({}):
        session.merge(
            AnimeGroupSetting(
                "CC", str(doc["_id"]), "usr", None, user_id=doc.get("usr")
            )
        )
        channels += 1
    report("anime[CC]", channels)

    ui = 0
    for doc in mongo["GROUP_UI"].find({}):
        chat_id = str(doc["_id"])
        for field in ("bl", "cs"):
            session.merge(AnimeGroupSetting("GUI", chat_id, field, doc.get(field)))
            ui += 1
    report("anime[GUI]", ui)

    tokens = 0
    for doc in mongo["AUTH_USERS"].find({}):
        if "id" in doc and "token" in doc:
            session.merge(AnimeToken(int(doc["id"]), doc["token"]))
            tokens += 1
    report("anime_tokens", tokens)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without touching PostgreSQL",
    )
    args = parser.parse_args()

    mongo = mongo_db()
    session = NullSession() if args.dry_run else load_models()
    lines = []

    def report(table, count):
        lines.append(f"  {table:<28} {count}")

    try:
        for step in (
            backfill_whispers,
            backfill_locale,
            backfill_toggles,
            backfill_karma,
            backfill_sangmata,
            backfill_anime,
        ):
            step(mongo, session, report)
    except Exception:
        # A partial backfill is worse than none: the transaction below would
        # never run, so nothing is written, but say so rather than exiting 0.
        print("backfill failed, nothing was written", file=sys.stderr)
        raise

    if args.dry_run:
        print(f"dry run, nothing written ({session.would_write} rows would be upserted):")
    else:
        session.commit()
        print("written in one transaction:")
    print("\n".join(lines))
    print("\nDC (disabled commands) is not read from Mongo: /disable has always "
          "written PostgreSQL, so anime.py now reads the same table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
