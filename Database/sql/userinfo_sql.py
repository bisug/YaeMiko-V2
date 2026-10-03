"""The (name, username) pair the ban handlers show when they mention a user.

The Mongo document these handlers used to read carried a "name" key. The
PostgreSQL `users` table never had one, so name is always None here and each
caller falls back to its own "user(<id>)" placeholder. Returning the Mongo key
set anyway keeps the call sites unchanged and leaves room for a name column
if one is ever added.
"""

from Database.sql import unit_of_work_guard
from Database.sql.users_sql import Users, get_name_by_userid, get_userid_by_name


@unit_of_work_guard
def get_user_info(user_id_or_name) -> dict:
    if isinstance(user_id_or_name, str):
        matches = get_userid_by_name(user_id_or_name.lstrip("@"))
        user = matches[0] if matches else None
    else:
        user = get_name_by_userid(int(user_id_or_name))

    if not user:
        return {}
    return {"name": None, "username": user.username}


# Re-exported so callers can drop the Mongo import without a second one.
__all__ = ["Users", "get_user_info"]
