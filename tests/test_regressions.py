import ast
import asyncio
import threading
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def load_nested_function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


class FakeQuery:
    def __init__(self):
        self.filters = []

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def delete(self, synchronize_session=False):
        return 1


    def all(self):
        return []


class FakeSession:
    def __init__(self, federation):
        self.federation = federation
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.closed = False

    def __call__(self):
        return self

    def close(self):
        self.closed = True

    def get(self, model, key):
        return self.federation

    def query(self, model):
        return FakeQuery()

    def delete(self, instance):
        self.deleted.append(instance)

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollbacks += 1

class CleanmodeCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_cleanmode_is_cached(self):
        calls = 0

        class Collection:
            async def find_one(self, query):
                nonlocal calls
                calls += 1
                return {"chat_id": query["chat_id"]}

        namespace = {"cleanmode": {}, "cleandb": Collection()}
        is_cleanmode_on = load_function(
            ROOT / "Database/mongodb/afk_db.py",
            "is_cleanmode_on",
            namespace,
        )

        self.assertFalse(await is_cleanmode_on(123))
        self.assertFalse(await is_cleanmode_on(123))
        self.assertEqual(calls, 1)



class EnvironmentTests(unittest.TestCase):
    def test_ptb_application_is_imported(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn(
            ("telegram.ext", "Application"),
            {
                (node.module, alias.name)
                for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module
                for alias in node.names
            },
        )

    def test_ptb_persistence_is_configured_for_context_data(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            (node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        self.assertIn(("telegram.ext", "PicklePersistence"), imports)
        self.assertIn(("telegram.ext", "PersistenceInput"), imports)
        self.assertIn("PicklePersistence(", source)
        self.assertIn(".persistence(persistence)", source)
        self.assertIn("chat_data=True", source)
        self.assertIn("user_data=True", source)
        self.assertIn("bot_data=False", source)
        self.assertIn("callback_data=False", source)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("ptb_persistence.pickle", gitignore)

    def test_start_escapes_markdown_with_imported_helper(self):
        tree = ast.parse((ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8"))
        imports = {
            (node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        self.assertIn(("telegram.helpers", "escape_markdown"), imports)

    def test_ptb_updates_are_processed_concurrently(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        self.assertIn(".concurrent_updates(64)", source)
        self.assertIn("from telegram.ext import AIORateLimiter, Application", source)
        self.assertIn(".rate_limiter(AIORateLimiter())", source)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("python-telegram-bot[rate-limiter,job-queue]==22.8", requirements)

    def test_disabled_antiflood_skips_admin_lookup(self):
        source = (ROOT / "Mikobot/plugins/flood.py").read_text(encoding="utf-8")
        early_return = "if sql.get_flood_limit(chat.id) == 0:\n        return \"\""
        self.assertLess(
            source.index(early_return),
            source.index("if await is_user_admin(chat, user.id):"),
        )

    def test_message_hot_paths_fail_fast(self):
        afk_source = (ROOT / "Mikobot/plugins/afk.py").read_text(encoding="utf-8")
        self.assertIn("if not sql.is_afk(user.id):\n        return", afk_source)

        gban_source = (ROOT / "Mikobot/plugins/gban.py").read_text(encoding="utf-8")
        gban_tree = ast.parse(gban_source)
        enforce_gban = next(
            node
            for node in gban_tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "enforce_gban"
        )
        gban_body = ast.get_source_segment(gban_source, enforce_gban)
        self.assertLess(
            gban_body.index("if not sql.does_chat_gban(chat.id):"),
            gban_body.index("await chat.get_member(bot.id)"),
        )

        locks_source = (ROOT / "Mikobot/plugins/locks.py").read_text(encoding="utf-8")
        locks_tree = ast.parse(locks_source)
        del_lockables = next(
            node
            for node in locks_tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "del_lockables"
        )
        locks_body = ast.get_source_segment(locks_source, del_lockables)
        self.assertLess(
            locks_body.index("locks = sql.get_locks(chat.id)"),
            locks_body.index("await chat.get_member(context.bot.id)"),
        )
        self.assertNotIn("sql.is_locked(chat.id, lockable)", locks_body)

    def test_kurigram_handlers_pass_callback_before_filter(self):
        tree = ast.parse((ROOT / "Mikobot/events.py").read_text(encoding="utf-8"))
        calls = {
            node.func.id: node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for handler_name in ("MessageHandler", "InlineQueryHandler", "CallbackQueryHandler"):
            args = calls[handler_name].args
            self.assertIsInstance(args[0].func, ast.Name, handler_name)
            self.assertEqual(args[0].func.id, "_with_client", handler_name)
            self.assertEqual(args[1].id, "handler_filter", handler_name)

    def test_plugin_imports_do_not_import_main(self):
        for path in (ROOT / "Mikobot/plugins/ping.py", ROOT / "Mikobot/plugins/info.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertFalse(
                any(
                    isinstance(node, ast.ImportFrom)
                    and node.module == "Mikobot.__main__"
                    for node in tree.body
                ),
                path.name,
            )


    def test_quotely_uses_supported_entity_types(self):
        source = (ROOT / "Mikobot/plugins/quotely.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            (node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        self.assertIn(("pyrogram.enums", "MessageEntityType"), imports)
        self.assertNotIn("MessageEntityPhone", source)

    def test_kurigram_lifecycle_uses_sync_wrappers(self):
        source = (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8")
        self.assertIn("        app.start()", source)
        self.assertIn("            app.stop()", source)
        self.assertNotIn("run_until_complete(app.start())", source)
        self.assertNotIn("run_until_complete(app.stop())", source)


        self.assertNotIn("MessageEntityPhone", source)


    def test_boolean_values_are_explicit(self):
        env_bool = load_function(
            ROOT / "Mikobot/__init__.py",
            "env_bool",
            {"os": __import__("os")},
        )
        for value in ("1", "true", "yes", "on"):
            with mock.patch.dict(__import__("os").environ, {"TEST_FLAG": value}):
                self.assertTrue(env_bool("TEST_FLAG"))
        for value in ("0", "false", "no", "off"):
            with mock.patch.dict(__import__("os").environ, {"TEST_FLAG": value}):
                self.assertFalse(env_bool("TEST_FLAG"))
        with mock.patch.dict(__import__("os").environ, {"TEST_FLAG": "invalid"}):
            with self.assertRaises(ValueError):
                env_bool("TEST_FLAG")

    def test_waitlist_is_scoped_to_chat_and_user(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/welcome.py").read_text(encoding="utf-8"))
        source = ast.unparse(tree)
        self.assertIn("(chat.id, new_mem.id)", source)
        self.assertIn("VERIFIED_USER_WAITLIST.pop((chat_id, member.id), None)", source)
        self.assertIn("waitlist_key = (chat.id, user.id)", source)


class BroadcastParsingTests(unittest.TestCase):
    def setUp(self):
        self.parse = load_function(
            ROOT / "Mikobot/plugins/users.py",
            "parse_broadcast_request",
            {"BROADCAST_TARGETS": {"-all", "-group", "-user"}},
        )

    def test_all_target_expands_without_becoming_content(self):
        targets, content = self.parse("/gcast -all hello world")
        self.assertEqual(targets, {"-all", "-group", "-user"})
        self.assertEqual(content, "hello world")

    def test_content_can_precede_target(self):
        targets, content = self.parse("/gcast announcement -group")
        self.assertEqual(targets, {"-group"})
        self.assertEqual(content, "announcement")

    def test_reply_allows_missing_inline_content(self):
        targets, content = self.parse("/gcast -all", has_reply=True)
        self.assertEqual(targets, {"-all", "-group", "-user"})
        self.assertIsNone(content)

    def test_non_reply_without_content_is_rejected(self):
        targets, content = self.parse("/gcast -all")
        self.assertEqual(targets, {"-all", "-group", "-user"})
        self.assertIsNone(content)

    def test_group_inventory_requires_developer_access(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/users.py").read_text(encoding="utf-8"))
        chats = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "chats"
        )
        decorators = [ast.unparse(node) for node in chats.decorator_list]
        self.assertIn("check_admin(only_dev=True)", decorators)


class StartupTests(unittest.TestCase):
    def test_event_loop_is_explicit_on_python_314(self):
        create_loop = load_function(
            ROOT / "Mikobot/__init__.py",
            "_create_event_loop",
            {"asyncio": asyncio},
        )
        loop = create_loop()
        try:
            self.assertIs(asyncio.get_event_loop(), loop)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_runtime_bot_names_are_dynamic(self):
        karma = (ROOT / "Infamous/karma.py").read_text(encoding="utf-8")
        info = (ROOT / "Mikobot/plugins/info.py").read_text(encoding="utf-8")
        init = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")

        self.assertIn("PM_START_TEXT = f", karma)
        self.assertIn("HELP_STRINGS = f", karma)
        self.assertIn("escape_markdown(BOT_NAME)", karma)
        self.assertIn("escape(BOT_NAME)", info)
        self.assertIn("Client(BOT_USERNAME", init)
        for hardcoded_name in ("ɪ ᴀᴍ ᴍɪᴋᴏ", "Yae-Miko", "Yae Miko Bot"):
            self.assertNotIn(hardcoded_name, karma + info)

    def test_startup_fetches_and_displays_bot_identity(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("dispatcher.bot.initialize()"),
            source.index("dispatcher.bot.get_me()"),
        )
        self.assertIn("BOT_ID = bot_info.id", source)
        self.assertIn("BOT_NAME = bot_info.first_name", source)
        self.assertIn("BOT_USERNAME = bot_info.username", source)
        self.assertIn("escape(BOT_NAME)", source)
        self.assertIn("escape(BOT_USERNAME)", source)
        self.assertIn("{BOT_ID}", source)




class FederationDeletionTests(unittest.TestCase):
    def namespace(self, session, owner="123"):
        return {
            "FEDS_LOCK": threading.RLock(),
            "Federations": object,
            "ChatF": SimpleNamespace(fed_id=object()),
            "BansF": SimpleNamespace(fed_id=object()),
            "FedSubs": SimpleNamespace(fed_id=object()),
            "OWNER_ID": 999,
            "Session": lambda engine: session,
            "ENGINE": object(),
            "FEDERATION_BYOWNER": {owner: {}},
            "FEDERATION_BYFEDID": {"fed": {}},
            "FEDERATION_BYNAME": {"Federation": {}},
            "FEDERATION_CHATS_BYID": {"fed": ["-100"]},
            "FEDERATION_CHATS": {"-100": {}},
            "FEDERATION_BANNED_USERID": {"fed": [1]},
            "FEDERATION_BANNED_FULL": {"fed": {1: {}}},
            "FEDS_SUBSCRIBER": {"fed": {}},
            "MYFEDS_SUBSCRIBER": {"fed": {}},
        }

    def test_non_owner_cannot_delete(self):
        federation = SimpleNamespace(owner_id="123", fed_name="Federation")
        session = FakeSession(federation)
        namespace = self.namespace(session)
        delete = load_function(
            ROOT / "Database/sql/feds_sql.py", "del_fed", namespace
        )

        self.assertFalse(delete("fed", "456"))
        self.assertEqual(session.rollbacks, 0)
        self.assertEqual(session.deleted, [])
        self.assertTrue(session.closed)
        self.assertIn("fed", namespace["FEDERATION_BYFEDID"])

    def test_owner_deletion_commits_before_cache_removal(self):
        federation = SimpleNamespace(owner_id="123", fed_name="Federation")
        session = FakeSession(federation)
        namespace = self.namespace(session)
        state = {"committed": False}
        session.commit = lambda: state.update(committed=True)
        original_pop = namespace["FEDERATION_BYOWNER"].pop

        def checked_pop(key, *args):
            self.assertTrue(state["committed"])
            return original_pop(key, *args)

        namespace["FEDERATION_BYOWNER"] = SimpleNamespace(pop=checked_pop)
        delete = load_function(
            ROOT / "Database/sql/feds_sql.py", "del_fed", namespace
        )

        self.assertTrue(delete("fed", "123"))
        self.assertTrue(session.closed)
        self.assertNotIn("fed", namespace["FEDERATION_BYFEDID"])

    def test_failed_commit_rolls_back_and_preserves_cache(self):
        federation = SimpleNamespace(owner_id="123", fed_name="Federation")
        session = FakeSession(federation)
        session.fail_commit = True
        namespace = self.namespace(session)
        delete = load_function(
            ROOT / "Database/sql/feds_sql.py", "del_fed", namespace
        )

        self.assertFalse(delete("fed", "123"))
        self.assertEqual(session.rollbacks, 1)
        self.assertTrue(session.closed)
        self.assertIn("fed", namespace["FEDERATION_BYFEDID"])



class ElevatedUserTests(unittest.TestCase):
    def test_runtime_promotion_updates_lists_in_place(self):
        mikobot = SimpleNamespace(
            DEV_USERS=[1],
            CONFIG_SUDOS=set(),
            CONFIG_DEMONS=set(),
            CONFIG_WOLVES=set(),
            CONFIG_TIGERS=set(),
            DRAGONS=[1],
            DEMONS=[],
            WOLVES=[],
            TIGERS=[],
            SUPPORT_STAFF=[1],
            OWNER_ID=1,
        )
        dragons = mikobot.DRAGONS
        apply_users = load_function(
            ROOT / "Mikobot/plugins/disasters.py",
            "apply_elevated_users",
            {"Mikobot": mikobot},
        )
        apply_users(
            {
                "sudos": [2],
                "supports": [3],
                "whitelists": [4],
                "tigers": [5],
            }
        )

        self.assertIs(mikobot.DRAGONS, dragons)
        self.assertEqual(mikobot.DRAGONS, [1, 2])
        self.assertEqual(mikobot.DEMONS, [3])
        self.assertEqual(mikobot.WOLVES, [4])
        self.assertEqual(mikobot.TIGERS, [5])
        self.assertEqual(mikobot.SUPPORT_STAFF, [1, 2, 4, 3])


class FederationCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_rejects_a_different_user(self):
        calls = []

        class Message:
            chat = SimpleNamespace(type="private")

            async def edit_text(self, *args, **kwargs):
                raise AssertionError("invalid callback must not edit the message")

        query = SimpleNamespace(
            data="rmfed_fed:123",
            from_user=SimpleNamespace(id=456),
            message=Message(),
            answer=self._record_answer,
        )
        sql = SimpleNamespace(
            get_fed_info=lambda fed_id: {"fname": "Federation"},
            del_fed=lambda *args: calls.append(args),
        )
        delete = load_function(
            ROOT / "Mikobot/plugins/feds.py",
            "del_fed_button",
            {
                "sql": sql,
                "is_user_fed_owner": lambda *args: True,
                "ParseMode": SimpleNamespace(MARKDOWN="Markdown"),
                "Update": object,
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
            },
        )

        await delete(SimpleNamespace(callback_query=query), SimpleNamespace())
        self.assertEqual(calls, [])

    async def _record_answer(self, *args, **kwargs):
        self.answer = (args, kwargs)


class RuntimeDefectTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_log_failure_preserves_chat_logging(self):
        stopped = []

        class BadRequest(Exception):
            def __init__(self, message):
                self.message = message
                super().__init__(message)

        class Bot:
            async def send_message(self, chat_id, *args, **kwargs):
                if chat_id == "-100":
                    raise BadRequest("Chat not found")
                return SimpleNamespace()

        send_log = load_nested_function(
            ROOT / "Mikobot/plugins/log_channel.py",
            "send_log",
            {
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
                "BadRequest": BadRequest,
                "ParseMode": SimpleNamespace(HTML="HTML"),
                "LinkPreviewOptions": SimpleNamespace,
                "LOGGER": SimpleNamespace(warning=lambda *args, **kwargs: None),
                "sql": SimpleNamespace(
                    get_chat_log_channel=lambda chat_id: "per-chat",
                    stop_chat_logging=lambda chat_id: stopped.append(chat_id),
                ),
            },
        )

        await send_log(SimpleNamespace(bot=Bot()), "-100", 42, "event")
        self.assertEqual(stopped, [])

    def test_federation_extractors_are_awaited(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/feds.py").read_text(encoding="utf-8"))
        source = ast.unparse(tree)
        self.assertIn("await extract_unt_fedban(message, context, args)", source)
        self.assertIn("await extract_user_fban(message, context, args)", source)

    def test_roar_uses_ptb_argument_order(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/ban.py").read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "selfunban"
        )
        self.assertEqual([arg.arg for arg in function.args.args], ["update", "context"])

    def test_rules_error_path_does_not_use_failed_chat(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/rules.py").read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_rules"
        )
        handler = next(node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler))
        names = {node.id for node in ast.walk(handler) if isinstance(node, ast.Name)}
        self.assertNotIn("chat", names)

    def test_missing_event_logs_are_not_stringified_or_sent(self):
        log_source = (ROOT / "Mikobot/plugins/log_channel.py").read_text(encoding="utf-8")
        self.assertNotIn("str(EVENT_LOGS)", log_source)
        self.assertIn("if EVENT_LOGS:", log_source)
        self.assertIn("if not is_chat_log:", log_source)

        for relative in ("Mikobot/plugins/feds.py", "Mikobot/plugins/welcome.py"):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            event_log_sends = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_message"
                and any(isinstance(arg, ast.Name) and arg.id == "EVENT_LOGS" for arg in node.args)
            ]
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            self.assertTrue(event_log_sends, relative)
            for call in event_log_sends:
                current = call
                while current in parents:
                    current = parents[current]
                    if isinstance(current, ast.If):
                        break
                self.assertIsInstance(current, ast.If, relative)

    def test_force_subscribe_skips_chat_privileged_members(self):
        source = (ROOT / "Mikobot/plugins/fsub.py").read_text(encoding="utf-8")
        self.assertIn("ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR", source)

    def test_kurigram_message_callbacks_accept_client_and_message(self):
        for relative, function_name in (
            ("Mikobot/plugins/fsub.py", "force_subscribe_new_message"),
            ("Mikobot/plugins/zombies.py", "zombies"),
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            function = next(
                node
                for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
            )
            self.assertEqual(len(function.args.args), 2, relative)

    def test_quotely_has_timeout_and_valid_fallback(self):
        source = (ROOT / "Mikobot/plugins/quotely.py").read_text(encoding="utf-8")
        self.assertIn("from Mikobot.state import state", source)
        self.assertIn("state.post", source)
        self.assertIn("state.get", source)
        self.assertIn("httpx.HTTPError", source)
        self.assertNotIn("aiohttp", source)
        self.assertIn("suffix=\".png\"", source)
        self.assertIn("image.convert(\"RGB\").save(file, format=\"PNG\")", source)
        self.assertNotIn("suffix=\".webp\"", source)
        self.assertIn("return await self.create_quotly(self._API)", source)
        self.assertIn("shnwazdev-quoteapi.vercel.app/quote/generate", source)
        self.assertNotIn("bot.lyo.su/quote/generate", source)
        self.assertIn("event.forward_origin", source)

        self.assertIn("event.command and len(event.command) > 1", source)

    def test_quotely_uses_kurigram_forward_origin(self):
        source = (ROOT / "Mikobot/plugins/quotely.py").read_text(encoding="utf-8")
        self.assertNotIn("event.fwd_from", source)
        self.assertIn("event.forward_origin", source)
        self.assertIn('getattr(forward_origin, "sender_user", None)', source)
        self.assertIn('getattr(forward_origin, "sender_user_name", None)', source)
        self.assertIn('getattr(forward_origin, "author_signature", None)', source)

    def test_pyrate_limiter_v4_uses_nonblocking_api(self):
        tree = ast.parse(
            (ROOT / "Mikobot/plugins/cust_filters.py").read_text(encoding="utf-8")
        )
        class_node = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AntiSpam"
        )
        module = ast.fix_missing_locations(ast.Module(body=[class_node], type_ignores=[]))

        calls = []

        class Duration:
            SECOND = 1
            MINUTE = 60
            HOUR = 3600
            DAY = 86400

        class Limiter:
            def __init__(self, bucket):
                self.bucket = bucket

            def try_acquire(self, user, **kwargs):
                calls.append((user, kwargs))
                return False

        namespace = {
            "DEV_USERS": [],
            "DRAGONS": [],
            "Duration": Duration,
            "Rate": lambda limit, interval: (limit, interval),
            "InMemoryBucket": lambda rates: rates,
            "Limiter": Limiter,
        }
        exec(compile(module, "cust_filters.py", "exec"), namespace)
        anti_spam = namespace["AntiSpam"]()

        self.assertTrue(anti_spam.check_user(123))
        self.assertEqual(calls, [(123, {"blocking": False})])

    def test_async_mongodb_uses_one_client_and_explicit_close(self):
        client_paths = [
            path
            for path in (ROOT / "Database/mongodb").glob("*.py")
            if "AsyncMongoClient(" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(client_paths, [ROOT / "Database/mongodb/db.py"])
        anime_source = (ROOT / "Mikobot/plugins/anime.py").read_text(encoding="utf-8")
        self.assertIn('mongo["MikobotAnime"]', anime_source)
        main_source = (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8")
        self.assertIn("close_db()", main_source)

    def test_sqlalchemy_uses_psycopg3_driver(self):
        source = (ROOT / "Database/sql/__init__.py").read_text(encoding="utf-8")
        self.assertIn('DB_URI.startswith(("postgres://", "postgresql://"))', source)
        self.assertIn('"postgresql+psycopg://"', source)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("psycopg[binary,pool]==3.3.6", requirements)
        self.assertNotIn("psycopg2-binary", requirements)

        ai_source = (ROOT / "Mikobot/plugins/ai.py").read_text(encoding="utf-8")
        self.assertIn('LOGGER.exception("Gemini request failed")', ai_source)
        self.assertIn("AutomaticFunctionCallingConfig", ai_source)
        self.assertIn("disable=True", ai_source)
        main_source = (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("markdownhelp", main_source)

        for relative in ("Mikobot/__init__.py", "variables.py", "app.json"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("gemini-3.5-flash-lite", source)
            if relative == "Mikobot/__init__.py":
                self.assertIn(
                    'if GEMINI_MODEL == "gemini-2.5-flash-lite"', source
                )
            else:
                self.assertNotIn("gemini-2.5-flash-lite", source)

    def test_confirmed_undefined_runtime_names_are_resolved(self):
        expected_imports = {
            "Mikobot/plugins/welcome.py": {("Mikobot", "SUPPORT_STAFF")},
            "Mikobot/plugins/disasters.py": {("telegram.helpers", "mention_html")},
            "Mikobot/plugins/tr.py": {("Mikobot.plugins.anime", "google_new_transError")},
        }
        for relative, required in expected_imports.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            imports = {
                (node.module, alias.name)
                for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module
                for alias in node.names
            }
            self.assertTrue(required <= imports, relative)

        main_tree = ast.parse((ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                isinstance(node, ast.Import)
                and any(alias.name == "html" for alias in node.names)
                for node in main_tree.body
            )
        )
        anime_source = (ROOT / "Mikobot/plugins/anime.py").read_text(encoding="utf-8")
        self.assertIn("gcc = get_user_from_channel", anime_source)
        self.assertNotIn("SESSION.query(UserF)", (ROOT / "Database/sql/feds_sql.py").read_text(encoding="utf-8"))
        for relative in (
            "Mikobot/plugins/helper_funcs/extraction.py",
            "Mikobot/plugins/users.py",
            "Mikobot/plugins/gban.py",
            "Mikobot/plugins/feds.py",
            "Mikobot/plugins/afk.py",
        ):
            self.assertNotIn("get_chat(user_id)", (ROOT / relative).read_text(encoding="utf-8"))


class PTBHandlerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_use_anonymous_unban_callback(self):
        bans_callback = load_function(
            ROOT / "Mikobot/plugins/ban.py",
            "bans_callback",
            {
                "Update": object,
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
                "ChatMemberAdministrator": type("Administrator", (), {}),
                "DRAGONS": [],
                "DEV_USERS": [],
                "OWNER_ID": 1,
                "html": __import__("html"),
                "ParseMode": SimpleNamespace(HTML="HTML"),
                "mention_html": lambda *args: "",
                "loggable": lambda function: function,
                "LOGGER": SimpleNamespace(
                    warning=lambda *args, **kwargs: None,
                    exception=lambda *args, **kwargs: None,
                ),
                "is_user_ban_protected": lambda *args: asyncio.sleep(0, False),
                "is_user_in_chat": lambda *args: asyncio.sleep(0, False),
                "BadRequest": Exception,
            },
        )
        unban_calls = []

        async def answer_query(*args, **kwargs):
            pass

        class Chat:
            id = 99
            type = "group"
            title = "Chat"
            is_forum = False

            async def get_member(self, user_id):
                return SimpleNamespace(status="member", user=SimpleNamespace(id=user_id))

            async def unban_member(self, user_id):
                unban_calls.append(user_id)

        class Message:
            async def edit_text(self, *args, **kwargs):
                pass

        query = SimpleNamespace(
            data="bans_99=unban=123=token",
            from_user=SimpleNamespace(id=456),
            message=Message(),
            answer=answer_query,
        )
        await bans_callback(
            SimpleNamespace(
                callback_query=query,
                effective_chat=Chat(),
                effective_message=Message(),
            ),
            SimpleNamespace(
                args=[],
                bot=SimpleNamespace(id=77),
                chat_data={"anon_ban_token": {}},
            ),
        )
        self.assertEqual(unban_calls, [])

    async def test_malformed_ptb_callbacks_are_answered_without_crashing(self):
        async def answer_query(*args, **kwargs):
            return None

        callbacks = [
            (
                "admin_callback",
                {"Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object), "loggable": lambda function: function},
                "admin_",
            ),
            (
                "bans_callback",
                {"Update": object, "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object), "loggable": lambda function: function},
                "bans_",
            ),
        ]
        for name, dependencies, data in callbacks:
            callback = load_function(ROOT / f"Mikobot/plugins/{'admin' if name == 'admin_callback' else 'ban'}.py", name, dependencies)
            await callback(
                SimpleNamespace(
                    callback_query=SimpleNamespace(
                        data=data, from_user=SimpleNamespace(id=1), answer=answer_query
                    ),
                    effective_chat=None,
                    effective_message=None,
                ),
                SimpleNamespace(args=[], bot=SimpleNamespace(), chat_data={}),
            )

        user_button = load_function(
            ROOT / "Mikobot/plugins/welcome.py",
            "user_button",
            {
                "Update": object,
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
                "re": __import__("re"),
            },
        )
        await user_button(
            SimpleNamespace(
                callback_query=SimpleNamespace(data="user_join_invalid", answer=answer_query),
                effective_chat=None,
                effective_user=SimpleNamespace(id=1),
                effective_message=None,
            ),
            SimpleNamespace(bot=SimpleNamespace()),
        )


    async def test_numeric_whispers_compare_the_stored_id(self):
        answers = []

        async def answer_callback_query(*args, **kwargs):
            answers.append((args, kwargs))

        show_whisper = load_function(
            ROOT / "Mikobot/plugins/whispers.py",
            "showWhisper",
            {
                "Update": object,
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
                "Whispers": SimpleNamespace(
                    del_whisper=lambda whisper_id: asyncio.sleep(0),
                    get_whisper=lambda whisper_id: asyncio.sleep(
                        0,
                        {
                            "user": 1,
                            "withuser": 2,
                            "usertype": "id",
                            "message": "secret",
                        },
                    )
                )
            },
        )
        await show_whisper(
            SimpleNamespace(
                callback_query=SimpleNamespace(
                    id="1",
                    data="whisper_x",
                    from_user=SimpleNamespace(id=2, username="alice"),
                )
            ),
            SimpleNamespace(
                bot=SimpleNamespace(answer_callback_query=answer_callback_query)
            ),
        )
        self.assertEqual(answers[0][0][1], "secret")

    async def test_overlong_inline_whispers_are_answered(self):
        answers = []

        class InlineQuery:
            query = "@alice " + "x" * 201
            from_user = SimpleNamespace(id=1)

            async def answer(self, *args, **kwargs):
                answers.append((args, kwargs))

        parse_user_message = load_function(
            ROOT / "Mikobot/plugins/whispers.py", "parse_user_message", {}
        )
        mainwhisper = load_function(
            ROOT / "Mikobot/plugins/whispers.py",
            "mainwhisper",
            {
                "Update": object,
                "ContextTypes": SimpleNamespace(DEFAULT_TYPE=object),
                "parse_user_message": parse_user_message,
            },
        )
        await mainwhisper(
            SimpleNamespace(inline_query=InlineQuery()),
            SimpleNamespace(bot=SimpleNamespace(answer_inline_query=lambda *args: None)),
        )
        self.assertEqual(len(answers), 1)

    def test_ptb_permission_calls_use_supported_fields(self):
        for relative in (
            "Mikobot/plugins/flood.py",
            "Mikobot/plugins/locks.py",
            "Mikobot/plugins/mute.py",
            "Mikobot/plugins/welcome.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("can_send_media_messages", source, relative)
            self.assertNotIn("can_send_invite_users", source, relative)
        self.assertIn('is_silent = parts[3] == "1"', (ROOT / "Mikobot/plugins/admin.py").read_text(encoding="utf-8"))
        self.assertIn("context.chat_data.pop", (ROOT / "Mikobot/plugins/ban.py").read_text(encoding="utf-8"))
        self.assertIn("Contact me in PM to get your current settings.", (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
