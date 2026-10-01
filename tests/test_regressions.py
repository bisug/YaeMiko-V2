import ast
import asyncio
import importlib
import re
import sys
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
        imports = {
            (node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        self.assertIn(("aiogram", "Bot"), imports)
        self.assertIn(("aiogram", "Dispatcher"), imports)
        self.assertIn("Dispatcher(storage=MemoryStorage())", source)

    def test_ptb_persistence_is_configured_for_context_data(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        self.assertIn("open_store(", source)
        self.assertIn("chat_data = store.chat_data", source)
        self.assertIn("user_data = store.user_data", source)
        persistence = (ROOT / "Mikobot/utils/persistence.py").read_text(encoding="utf-8")
        self.assertIn("def chat_data", persistence)
        self.assertIn("def user_data", persistence)
        self.assertIn("os.replace(tmp, self.filepath)", persistence)
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("ptb_persistence.pickle", gitignore)
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
        self.assertIn(("Mikobot.utils.parser", "escape_markdown"), imports)

    def test_ptb_updates_are_processed_concurrently(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        self.assertIn("session=ThrottledSession()", source)
        throttle = (ROOT / "Mikobot/utils/throttle.py").read_text(encoding="utf-8")
        self.assertIn("class ThrottledSession(AiohttpSession)", throttle)
        self.assertIn("async def make_request", throttle)
        jobs = (ROOT / "Mikobot/utils/jobs.py").read_text(encoding="utf-8")
        self.assertIn("AsyncIOScheduler", jobs)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("aiogram==3.31.0", requirements)
        self.assertNotIn("python-telegram-bot", requirements)

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
        # The cheap per-chat setting read must come before asking Telegram
        # whether this bot may restrict, or every group message costs an API
        # call even in chats that opted out.
        self.assertLess(
            gban_body.index("if not sql.does_chat_gban(chat.id):"),
            gban_body.index("await bot.get_chat_member(chat.id, bot.id)"),
        )

        locks_source = (ROOT / "Mikobot/plugins/locks.py").read_text(encoding="utf-8")
        locks_tree = ast.parse(locks_source)
        del_lockables = next(
            node
            for node in locks_tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "del_lockables"
        )
        locks_body = ast.get_source_segment(locks_source, del_lockables)
        # The cheap lock-table read must come before the API call for the bot's
        # own membership, or every message pays a round trip.
        self.assertLess(
            locks_body.index("locks = sql.get_locks(chat.id)"),
            locks_body.index("await bot.get_chat_member(chat.id, bot.id)"),
        )
        self.assertNotIn("sql.is_locked(chat.id, lockable)", locks_body)

    def test_rtl_lock_detects_arabic_script_without_a_dependency(self):
        has_arabic = load_function(
            ROOT / "Mikobot/plugins/locks.py",
            "_has_arabic_script",
            {"unicodedata": __import__("unicodedata")},
        )
        for text in ("مرحبا بالعالم", "سلام دنیا", "کھیل کا کھیل", "hello مرحبا world", "مُحَمَّد", "ﺁ"):
            with self.subTest(text=text):
                self.assertTrue(has_arabic(text))
        for text in (
            "hello world",
            "שלום עולם",
            "привет мир",
            "γειά σου κόσμε",
            "สวัสดีชาวโลก",
            "नमस्ते दुनिया",
            "12345",
            "٣٤٥",
            "\U0001f600\U0001f389",
            "",
        ):
            with self.subTest(text=text):
                self.assertFalse(has_arabic(text))

        locks_source = (ROOT / "Mikobot/plugins/locks.py").read_text(encoding="utf-8")
        self.assertNotIn("alphabet_detector", locks_source)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("alphabet-detector", requirements)

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
        # The Client name comes from the resolved identity, not a literal.
        self.assertIn("fetch_bot_info()[2]", init)
        for hardcoded_name in ("ɪ ᴀᴍ ᴍɪᴋᴏ", "Yae-Miko", "Yae Miko Bot"):
            self.assertNotIn(hardcoded_name, karma + info)

    def test_startup_fetches_and_displays_bot_identity(self):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        # The fetch happens inside fetch_bot_info(), not at import: a network
        # failure at import used to fail the whole test suite.
        self.assertIn("info = loop.run_until_complete(bot.me())", source)
        self.assertLess(
            source.index('LOGGER.info("Getting bot information")'),
            source.index("info = loop.run_until_complete(bot.me())"),
        )
        for name in ('if name == "BOT_ID":', 'if name == "BOT_NAME":', 'if name == "BOT_USERNAME":'):
            self.assertIn(name, source)
        self.assertIn("escape(bot_name)", source)
        self.assertIn("escape(bot_username)", source)
        self.assertIn("{bot_id}", source)




class FederationDeletionTests(unittest.TestCase):
    def namespace(self, session, owner="123"):
        return {
            "FEDS_LOCK": threading.RLock(),
            "Federations": object,
            "ChatF": SimpleNamespace(fed_id=object()),
            "BansF": SimpleNamespace(fed_id=object()),
            "FedSubs": SimpleNamespace(
                fed_id=object(), fed_subs=object()
            ),
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
            "SQLAlchemyError": RuntimeError,
            "LOGGER": SimpleNamespace(exception=lambda *args, **kwargs: None),
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
            },
        )

        await delete(query)
        self.assertEqual(calls, [])

    async def _record_answer(self, *args, **kwargs):
        self.answer = (args, kwargs)


class RuntimeDefectTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_log_failure_preserves_chat_logging(self):
        stopped = []

        class TelegramAPIError(Exception):
            def __init__(self, message):
                self.message = message
                super().__init__(message)

        class Bot:
            async def send_message(self, chat_id, *args, **kwargs):
                if chat_id == "-100":
                    raise TelegramAPIError("Chat not found")
                return SimpleNamespace()

        send_log = load_nested_function(
            ROOT / "Mikobot/plugins/log_channel.py",
            "send_log",
            {
                "TelegramAPIError": TelegramAPIError,
                "ParseMode": SimpleNamespace(HTML="HTML"),
                "LinkPreviewOptions": SimpleNamespace,
                "bot": Bot(),
                "LOGGER": SimpleNamespace(
                    warning=lambda *args, **kwargs: None,
                    exception=lambda *args, **kwargs: None,
                ),
                "sql": SimpleNamespace(
                    get_chat_log_channel=lambda chat_id: "per-chat",
                    stop_chat_logging=lambda chat_id: stopped.append(chat_id),
                ),
            },
        )

        await send_log("-100", 42, "event")
        self.assertEqual(stopped, [])

    async def test_error_handler_answers_failed_callback(self):
        answers = []
        warnings = []
        errors = []

        class TelegramAPIError(Exception):
            pass

        class CallbackQuery:
            def __init__(self):
                self.id = "callback-1"
                self.message = SimpleNamespace(
                    chat=SimpleNamespace(id=42),
                )
                self.answer = self.record_answer

            async def record_answer(self, *args, **kwargs):
                answers.append((args, kwargs))

        class Update:
            def __init__(self):
                self.event = CallbackQuery()
                self.exception = TelegramAPIError("failed")

        error_callback = load_function(
            ROOT / "Mikobot/__main__.py",
            "error_callback",
            {
                "Update": Update,
                "CallbackQuery": CallbackQuery,
                "TelegramAPIError": TelegramAPIError,
                "TelegramForbiddenError": TelegramAPIError,
                "TelegramServerError": TelegramAPIError,
                "TelegramNetworkError": TelegramAPIError,
                "TelegramRetryAfter": TelegramAPIError,
                "TelegramMigrateToChat": type("TelegramMigrateToChat", (TelegramAPIError,), {}),
                "_activity_summary": lambda event: "callback user=1 chat=42",
                "LOGGER": SimpleNamespace(
                    warning=lambda *args, **kwargs: warnings.append((args, kwargs)),
                    info=lambda *args, **kwargs: None,
                    error=lambda *args, **kwargs: errors.append((args, kwargs)),
                    debug=lambda *args, **kwargs: None,
                ),
            },
        )

        await error_callback(Update())
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0][1]["show_alert"])
        self.assertEqual(len(warnings), 1)

    async def test_audit_log_failure_does_not_fail_successful_action(self):
        async def failing_send_log(*args, **kwargs):
            raise RuntimeError("log delivery failed")

        async def successful_action(message):
            return "event"

        loggable = load_nested_function(
            ROOT / "Mikobot/plugins/log_channel.py",
            "loggable",
            {
                "wraps": __import__("functools").wraps,
                "ChatType": SimpleNamespace(SUPERGROUP="supergroup"),
                "send_log": failing_send_log,
                "sql": SimpleNamespace(get_chat_log_channel=lambda chat_id: -100),
                "LOGGER": SimpleNamespace(exception=lambda *args, **kwargs: None),
                "datetime": __import__("datetime").datetime,
                "timezone": __import__("datetime").timezone,
            },
        )
        message = SimpleNamespace(
            chat=SimpleNamespace(id=42, is_forum=False, username=None, type="private"),
            message_id=1,
            message_thread_id=None,
        )
        wrapped = loggable(successful_action)
        result = await wrapped(message)
        self.assertTrue(result.startswith("event\nEvent stamp:"))

    def test_federation_ban_functions_use_single_rollback_transaction(self):
        source = (ROOT / "Database/sql/feds_sql.py").read_text(encoding="utf-8")
        for name in ("fban_user", "multi_fban_user", "un_fban_user"):
            function = next(
                node
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            self.assertEqual(
                sum(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "commit"
                    for node in ast.walk(function)
                ),
                1,
                name,
            )
            self.assertFalse(any(isinstance(node, ast.Try) and node.finalbody for node in ast.walk(function)))

    def test_federation_extractors_are_awaited(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/feds.py").read_text(encoding="utf-8"))
        source = ast.unparse(tree)
        self.assertIn("await extract_unt_fedban(message, args)", source)
        self.assertIn("await extract_user_fban(message, args)", source)

    def test_roar_takes_message_and_command(self):
        tree = ast.parse((ROOT / "Mikobot/plugins/ban.py").read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "selfunban"
        )
        # aiogram injects by name, so the parameters are part of the contract.
        self.assertEqual([arg.arg for arg in function.args.args], ["message", "command"])

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
            "Mikobot/plugins/disasters.py": {("Mikobot.utils.parser", "mention_html")},
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

        main_source = (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("traceback.format_exception", main_source)
        self.assertIn("await failed.answer(", main_source)
        self.assertIn("_activity_summary(event)", main_source)
        for relative in (".gitignore", ".dockerignore"):
            self.assertIn("Logs.txt*", (ROOT / relative).read_text(encoding="utf-8"))
        init_source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("force=True", init_source)
        for relative in (
            "Mikobot/plugins/ban.py",
            "Mikobot/plugins/mute.py",
            "Mikobot/plugins/log_channel.py",
            "Mikobot/plugins/welcome.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("LOGGER.warning(update)", source)
            self.assertNotIn("LOGGER.warning(result)", source)
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


class DatabaseRegressionTests(unittest.TestCase):
    def test_sqlalchemy_pool_validates_and_recycles_connections(self):
        source = (ROOT / "Database/sql/__init__.py").read_text(encoding="utf-8")
        self.assertIn("pool_pre_ping=True", source)
        self.assertIn("pool_recycle=1800", source)

    def test_primary_key_lookups_replace_full_table_federation_scans(self):
        tree = ast.parse((ROOT / "Database/sql/feds_sql.py").read_text(encoding="utf-8"))
        for name in ("fban_user", "multi_fban_user", "un_fban_user", "get_fban_user"):
            function = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            self.assertFalse(
                any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "all"
                    for node in ast.walk(function)
                ),
                name,
            )

    def test_federation_ban_lookup_uses_composite_primary_key(self):
        class BanSession:
            def __init__(self):
                self.key = None
                self.closed = False

            def get(self, model, key):
                self.key = key
                return SimpleNamespace(reason="spam", time=60)

            def close(self):
                self.closed = True

        session = BanSession()
        get_fban_user = load_function(
            ROOT / "Database/sql/feds_sql.py",
            "get_fban_user",
            {
                "BansF": object,
                "FEDERATION_BANNED_USERID": {"fed": [123]},
                "SESSION": session,
            },
        )
        self.assertEqual(
            get_fban_user("fed", 123),
            (True, "spam", 60),
        )
        self.assertEqual(session.key, ("fed", "123"))
        self.assertTrue(session.closed)

    def test_all_inline_button_calls_have_explicit_styles(self):
        unstyled = []
        for path in list((ROOT / "Mikobot").rglob("*.py")) + [
            ROOT / "Infamous/karma.py"
        ]:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            aliases = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module in {
                    "telegram",
                    "pyrogram.types",
                }:
                    for alias in node.names:
                        if alias.name == "InlineKeyboardButton":
                            aliases.add(alias.asname or alias.name)
            if any(
                isinstance(node, ast.FunctionDef)
                and node.name == "paginate_modules"
                for node in tree.body
            ):
                aliases.add("EqInlineKeyboardButton")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in aliases
                    and not any(keyword.arg == "style" for keyword in node.keywords)
                ):
                    unstyled.append(f"{path}:{node.lineno}")
        self.assertEqual(unstyled, [])

    def test_telegram_at_constructors_use_aiogram_31_fields(self):
        # Skipped rather than failed when the pinned client is absent, so a
        # contributor without the dependency still gets a useful suite. CI
        # installs aiogram 3.31.0 and fails if the version differs, so this
        # assertion always runs there.
        try:
            import aiogram
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        from aiogram.types import (
            InlineQueryResultArticle,
            InputTextMessageContent,
            MenuButtonWebApp,
            WebAppInfo,
        )

        self.assertEqual(aiogram.__version__, "3.31.0")

        result = InlineQueryResultArticle(
            id="article-1",
            title="Article",
            thumbnail_url="https://example.com/thumb.jpg",
            input_message_content=InputTextMessageContent(message_text="text"),
        )
        self.assertEqual(result.thumbnail_url, "https://example.com/thumb.jpg")
        # aiogram makes MenuButtonWebApp.text required; PTB defaulted it.
        self.assertIsInstance(
            MenuButtonWebApp(
                text="Open", web_app=WebAppInfo(url="https://example.com")
            ).web_app,
            WebAppInfo,
        )

        chatadmin = (ROOT / "Mikobot/plugins/chatadmin.py").read_text(encoding="utf-8")
        misc = (ROOT / "Mikobot/plugins/helper_funcs/misc.py").read_text(encoding="utf-8")
        self.assertIn("MenuButtonWebApp(\n                text=command.args[1],\n                web_app=WebAppInfo(url=command.args[1]),", chatadmin)
        self.assertIn("thumbnail_url=thumb_url", misc)
        self.assertIn("id=str(uuid4())", misc)
        self.assertNotIn("thumb_url=thumb_url", misc)

    def test_no_ptb_only_keyword_arguments_survive(self):
        # PTB reply helpers took do_quote=; neither aiogram nor kurigram
        # accepts it, so any survivor raises TypeError at call time rather
        # than at import. Eleven of these were live across the migrated
        # plugins, so this checks every send/reply call site.
        removed = {"do_quote", "quote"}
        offenders = []
        for path in ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in {
                    "answer",
                    "reply",
                    "reply_text",
                    "send_message",
                    "send_photo",
                    "send_document",
                    "send_video",
                    "send_audio",
                    "send_voice",
                    "send_sticker",
                }:
                    continue
                for keyword in node.keywords:
                    if keyword.arg in removed:
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{node.lineno} {func.attr}({keyword.arg}=...)"
                        )
        self.assertEqual(offenders, [])

    def test_command_filters_are_constructed_correctly(self):
        # Command() takes `commands` keyword-only. A list or tuple passed
        # positionally lands in *values and is rejected as a non-string
        # pattern, which raised ValueError at import and stopped the bot
        # from starting. This walks every Command() call in Mikobot/ so that
        # failure is caught by the suite instead of at startup.
        try:
            import inspect

            from aiogram.filters import Command
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        bad = []
        if not inspect.signature(Command).parameters["commands"].kind.name.endswith(
            "KEYWORD_ONLY"
        ):
            bad.append("Command() no longer takes commands keyword-only")
        for path in sorted((ROOT / "Mikobot").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Name) and node.func.id == "Command"):
                    continue
                for arg in node.args:
                    # The positional forms still accepted are a plain string
                    # literal and a single Name bound to one (a loop over
                    # command names). Anything else -- a list or tuple -- is
                    # the bug.
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        continue
                    if isinstance(arg, ast.Name):
                        continue
                    bad.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} "
                        "Command() needs commands="
                    )
        self.assertEqual(bad, [])

    def test_note_and_filter_buttons_commit_with_their_parent(self):
        for relative, names in {
            "Database/sql/notes_sql.py": {"add_note_to_db"},
            "Database/sql/cust_filters_sql.py": {"add_filter", "new_add_filter"},
        }.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for name in names:
                function = next(
                    node
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name
                )
                commits = [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "commit"
                ]
                self.assertEqual(len(commits), 1, f"{relative}:{name}")

    def test_cleaner_and_lock_reset_targets_are_valid(self):
        cleaner = (ROOT / "Database/sql/cleaner_sql.py").read_text(encoding="utf-8")
        self.assertIn("curr.is_enable = is_enable", cleaner)
        self.assertIn("SESSION.delete(unignored)", cleaner)
        locks = (ROOT / "Database/sql/locks_sql.py").read_text(encoding="utf-8")
        self.assertIn("if reset and curr_perm:", locks)
        self.assertIn("if reset and curr_restr:", locks)
        users = (ROOT / "Database/sql/users_sql.py").read_text(encoding="utf-8")
        self.assertIn("return SESSION.get(Users, int(user_id))", users)
        self.assertNotIn("ChatMembers.query", users)



    def test_user_database_freshness_uses_value_equality(self):
        source = (ROOT / "Mikobot/plugins/users.py").read_text(encoding="utf-8")
        self.assertIn(
            "return USER_DB_CACHE.get(key) == (username, chat_name)", source
        )
        self.assertNotIn(
            "return (username, chat_name) in USER_DB_CACHE.get(key, ())", source
        )

    def test_federation_subscription_lookups_and_startup_cache(self):
        get_spec_subs = load_function(
            ROOT / "Database/sql/feds_sql.py",
            "get_spec_subs",
            {"FEDS_SUBSCRIBER": {"source": {"other"}}},
        )
        self.assertFalse(get_spec_subs("source", "target"))

        class SubscriptionSession:
            def __init__(self):
                self.closed = False

            def query(self, model):
                return SimpleNamespace(
                    all=lambda: [
                        SimpleNamespace(fed_id="source", fed_subs="target")
                    ]
                )

            def close(self):
                self.closed = True

        session = SubscriptionSession()
        namespace = {
            "SESSION": session,
            "FedSubs": object,
            "FEDS_SUBSCRIBER": {"stale": {"value"}},
            "MYFEDS_SUBSCRIBER": {"stale": {"value"}},
        }
        load_function(
            ROOT / "Database/sql/feds_sql.py", "__load_feds_subscriber", namespace
        )()
        self.assertEqual(namespace["FEDS_SUBSCRIBER"], {"source": {"target"}})
        self.assertEqual(namespace["MYFEDS_SUBSCRIBER"], {"target": {"source"}})
        self.assertTrue(session.closed)

    def test_federation_deletion_removes_incoming_subscriptions(self):
        source = (ROOT / "Database/sql/feds_sql.py").read_text(encoding="utf-8")
        self.assertIn(
            "(FedSubs.fed_id == fed_id) | (FedSubs.fed_subs == fed_id)", source
        )

    def test_federation_ban_mutations_update_caches_incrementally(self):
        tree = ast.parse((ROOT / "Database/sql/feds_sql.py").read_text(encoding="utf-8"))
        for name in ("fban_user", "multi_fban_user", "un_fban_user"):
            function = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            self.assertFalse(
                any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "__load_all_feds_banned"
                    for node in ast.walk(function)
                ),
                name,
            )

    def test_connection_history_uses_chat_ids_as_cache_keys(self):
        class History:
            def __init__(self, user_id, chat_id, chat_name, conn_time):
                self.user_id = user_id
                self.chat_id = chat_id
                self.chat_name = chat_name
                self.conn_time = conn_time

        class Session:
            def get(self, model, key):
                return None

            def add(self, value):
                pass

            def delete(self, value):
                pass

            def commit(self):
                pass

        cache = {}
        add_history = load_function(
            ROOT / "Database/sql/connection_sql.py",
            "add_history_conn",
            {
                "CONNECTION_HISTORY_LOCK": threading.RLock(),
                "ConnectionHistory": History,
                "HISTORY_CONNECT": cache,
                "SESSION": Session(),
                "time": SimpleNamespace(time=lambda: 1700000000),
            },
        )
        add_history(1, "-100", "first")
        add_history(1, "-200", "second")
        self.assertEqual(set(cache[1]), {"-100", "-200"})

    def test_federation_empty_reverse_subscription_cache_is_safe(self):
        get_mysubs = load_function(
            ROOT / "Database/sql/feds_sql.py",
            "get_mysubs",
            {"MYFEDS_SUBSCRIBER": {}},
        )
        self.assertEqual(get_mysubs("missing"), [])

    def test_connection_checks_run_database_access_off_event_loop(self):
        source = (ROOT / "Mikobot/plugins/connection.py").read_text(encoding="utf-8")
        self.assertIn(
            "connection = await asyncio.to_thread(sql.get_connected_chat, user_id)",
            source,
        )
        self.assertIn(
            "await asyncio.to_thread(sql.disconnect, user_id)", source
        )
        self.assertNotIn("disconnect_chat(update, bot)", source)

    def test_reminder_startup_preserves_same_timestamp_entries(self):
        class Reminder:
            def __init__(self, chat_id):
                self.chat_id = chat_id
                self.time_seconds = 200
                self.remind_message = chat_id
                self.user_id = 1

        class Session:
            def query(self, model):
                return SimpleNamespace(
                    all=lambda: [Reminder("chat1"), Reminder("chat2")]
                )

            def close(self):
                pass

        reminders = {}
        load_function(
            ROOT / "Database/sql/remind_sql.py",
            "__get_all_reminds",
            {
                "Reminds": object,
                "SESSION": Session(),
                "REMINDERS": reminders,
                "time": SimpleNamespace(time=lambda: 0),
                "rem_remind": lambda *args: True,
            },
        )()
        self.assertEqual(
            [item["chat_id"] for item in reminders[200]],
            ["chat1", "chat2"],
        )


class PTBHandlerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_use_anonymous_unban_callback(self):
        bans_callback = load_function(
            ROOT / "Mikobot/plugins/ban.py",
            "bans_callback",
            {
                "ChatMemberStatus": SimpleNamespace(
                    ADMINISTRATOR="administrator", CREATOR="creator"
                ),
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
                "TelegramAPIError": Exception,
                "bot": SimpleNamespace(id=77),
                "chat_data": {"anon_ban_token": {}},
                "store": SimpleNamespace(save=lambda: None),
                "F": SimpleNamespace(),
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

        class Message:
            chat = Chat()
            message_id = 1
            message_thread_id = None

            async def edit_text(self, *args, **kwargs):
                pass

        class FakeBot:
            id = 77

            async def get_chat_member(self, chat_id, user_id):
                return SimpleNamespace(status="member", user=SimpleNamespace(id=user_id))

            async def unban_chat_member(self, chat_id, user_id):
                unban_calls.append(user_id)

        bans_callback.__globals__["bot"] = FakeBot()

        query = SimpleNamespace(
            data="bans_99=unban=123=token",
            from_user=SimpleNamespace(id=456),
            message=Message(),
            answer=answer_query,
        )
        await bans_callback(query)
        self.assertEqual(unban_calls, [])

    async def test_malformed_ptb_callbacks_are_answered_without_crashing(self):
        async def answer_query(*args, **kwargs):
            return None

        # Malformed callback data must be answered, not raised. All three
        # now take the CallbackQuery directly.
        admin_callback = load_function(
            ROOT / "Mikobot/plugins/admin.py",
            "admin_callback",
            {
                "loggable": lambda function: function,
            },
        )
        await admin_callback(
            SimpleNamespace(
                data="admin_",
                from_user=SimpleNamespace(id=1),
                message=SimpleNamespace(chat=SimpleNamespace(id=5)),
                answer=answer_query,
            ),
        )

        bans_callback = load_function(
            ROOT / "Mikobot/plugins/ban.py",
            "bans_callback",
            {
                "loggable": lambda function: function,
                "chat_data": {},
                "store": SimpleNamespace(save=lambda: None),
            },
        )
        await bans_callback(
            SimpleNamespace(
                data="bans_",
                from_user=SimpleNamespace(id=1),
                message=SimpleNamespace(
                    chat=SimpleNamespace(id=5, type="group", title="c", is_forum=False)
                ),
                answer=answer_query,
            ),
        )

        user_button = load_function(
            ROOT / "Mikobot/plugins/welcome.py",
            "user_button",
            {
                "re": __import__("re"),
            },
        )
        await user_button(
            SimpleNamespace(
                data="user_join_invalid",
                from_user=SimpleNamespace(id=1),
                message=SimpleNamespace(chat=SimpleNamespace(id=5)),
                answer=answer_query,
            ),
        )


    async def test_numeric_whispers_compare_the_stored_id(self):
        # The recipient is matched by id, not by username: an @alice with a
        # different numeric id must still see the whisper.
        answers = []

        class CallbackQuery:
            id = "1"
            data = "whisper_x"
            from_user = SimpleNamespace(id=2, username="alice")

            async def answer(self, text, **kwargs):
                answers.append((text, kwargs))

        show_whisper = load_function(
            ROOT / "Mikobot/plugins/whispers.py",
            "showWhisper",
            {
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
        await show_whisper(CallbackQuery())
        self.assertEqual(answers[0][0], "secret")

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
            {"parse_user_message": parse_user_message},
        )
        await mainwhisper(InlineQuery())
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
        self.assertIn('chat_data.pop(f"anon_ban_{parts[3]}", None)', (ROOT / "Mikobot/plugins/ban.py").read_text(encoding="utf-8"))
        self.assertIn("Contact me in PM to get your current settings.", (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8"))


class RepositoryGateTests(unittest.TestCase):
    """The deployment and documentation gates CI runs, so they cannot rot."""

    def _errors(self, module_name):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        module = importlib.import_module(module_name)
        errors = []
        for name in dir(module):
            if name.startswith("check_"):
                getattr(module, name)(errors)
        return errors

    def test_deployment_manifests_are_valid(self):
        self.assertEqual(self._errors("validate_deployment"), [])

    def test_documentation_is_valid(self):
        self.assertEqual(self._errors("validate_docs"), [])


class ElevatedUserBaselineTests(unittest.TestCase):
    """CONFIG_* baselines must be captured after elevated users and the owner are
    merged, otherwise apply_elevated_users rebuilds the runtime lists without
    them and promoted users silently lose their tier on the next promotion."""

    def _resolve(self, body):
        """Execute the SETS block of Mikobot/__init__.py with a fake _load_elevated_users."""
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        start = source.index("ELEVATED_USERS = _load_elevated_users()")
        end = source.index("# <============================================== INITIALIZE APPLICATION")
        block = source[start:end]
        namespace = {
            "OWNER_ID": 5,
            "DRAGONS": {10},
            "DEV_USERS": set(),
            "WOLVES": set(),
            "DEMONS": set(),
            "TIGERS": set(),
            "_load_elevated_users": lambda: {
                "sudos": [99],
                "supports": [98],
                "whitelists": [97],
                "tigers": [96],
            },
        }
        exec(compile(block, "__init_sets__.py", "exec"), namespace)
        return namespace

    def test_baselines_include_elevated_users_and_owner(self):
        namespace = self._resolve(None)
        self.assertEqual(namespace["CONFIG_SUDOS"], {5, 10, 99})
        self.assertEqual(namespace["CONFIG_DEMONS"], {98})
        self.assertEqual(namespace["CONFIG_WOLVES"], {97})
        self.assertEqual(namespace["CONFIG_TIGERS"], {96})

    def test_promotion_preserves_owner_and_promoted_users(self):
        namespace = self._resolve(None)
        mikobot = SimpleNamespace(
            DEV_USERS=list(namespace["DEV_USERS"]),
            CONFIG_SUDOS=namespace["CONFIG_SUDOS"],
            CONFIG_DEMONS=namespace["CONFIG_DEMONS"],
            CONFIG_WOLVES=namespace["CONFIG_WOLVES"],
            CONFIG_TIGERS=namespace["CONFIG_TIGERS"],
            # The end of __init__ rebinds these tiers to lists.
            DRAGONS=list(namespace["DRAGONS"]),
            DEMONS=list(namespace["DEMONS"]),
            WOLVES=list(namespace["WOLVES"]),
            TIGERS=list(namespace["TIGERS"]),
            SUPPORT_STAFF=[5],
            OWNER_ID=5,
        )
        apply_users = load_function(
            ROOT / "Mikobot/plugins/disasters.py",
            "apply_elevated_users",
            {"Mikobot": mikobot},
        )
        apply_users(
            {
                "sudos": [99],
                "supports": [98],
                "whitelists": [97],
                "tigers": [96],
            }
        )
        # The owner and the previously promoted sudo must survive the rebuild.
        self.assertIn(5, mikobot.DRAGONS)
        self.assertIn(99, mikobot.DRAGONS)
        self.assertIn(5, mikobot.SUPPORT_STAFF)


class ChatStatusPrecedenceTests(unittest.TestCase):
    """`else False or user.id in DRAGONS` parses as `else (False or ... in DRAGONS)`.
    An admin lacking the specific permission short-circuits to False and a sudo
    user is wrongly denied, so the DRAGONS check has to sit outside the ternary.
    The check now lives in the gate middleware, so it is asserted there."""

    def test_sudo_user_is_allowed_even_without_the_permission(self):
        gate = (ROOT / "Mikobot/utils/gate.py").read_text(encoding="utf-8")
        self.assertNotIn("else False or user.id in DRAGONS", gate)
        self.assertIn("or user_id in status.DRAGONS", gate)

class MarkdownEscapingTests(unittest.TestCase):
    """telegram.helpers.escape_markdown has no aiogram counterpart for the legacy
    Markdown mode, so Mikobot/utils/parser.py keeps the escaping. This pins it
    against PTB's implementation while PTB is still installed."""

    def test_matches_python_telegram_bot(self):
        try:
            from telegram.helpers import escape_markdown as ptb
        except ModuleNotFoundError:
            self.skipTest("python-telegram-bot is not installed")
        ours = load_function(
            ROOT / "Mikobot/utils/parser.py",
            "escape_markdown",
            {"sub": re.sub},
        )
        for text in ("a_b*c`d[e]f", "plain text", "_*`["):
            with self.subTest(text=text):
                self.assertEqual(ours(text), ptb(text, 1))


class LockPredicateTests(unittest.TestCase):
    """del_lockables() deletes messages, so each LOCK_TYPES entry must match
    only its own content. They are plain callables, not aiogram magic filters:
    F.<attr>(event) composes a filter rather than evaluating one, which would
    have made every lockable match every message."""

    def _locks(self):
        source = (ROOT / "Mikobot/plugins/locks.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        wanted = {"_has_entity", "_is_command", "LOCK_TYPES"}
        body = [
            node
            for node in tree.body
            if (isinstance(node, ast.FunctionDef) and node.name in wanted)
            or (
                isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", None) in wanted
            )
        ]
        namespace = {}
        exec(
            compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), "locks", "exec"),
            namespace,
        )
        return namespace["LOCK_TYPES"]

    @staticmethod
    def _message(**kwargs):
        base = dict(
            text=None,
            caption=None,
            entities=None,
            caption_entities=None,
            audio=None,
            voice=None,
            document=None,
            video=None,
            contact=None,
            photo=None,
            forward_date=None,
            game=None,
            location=None,
            dice=None,
            video_note=None,
            sticker=None,
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    def test_each_lockable_matches_only_its_own_content(self):
        entity = lambda kind: SimpleNamespace(type=kind, offset=0, length=1)
        locks = self._locks()
        cases = [
            ("audio", self._message(audio=1), True),
            ("audio", self._message(text="hi"), False),
            ("photo", self._message(photo=[1]), True),
            ("photo", self._message(text="hi"), False),
            ("url", self._message(text="x", entities=[entity("url")]), True),
            ("url", self._message(caption="x", caption_entities=[entity("url")]), True),
            ("url", self._message(text="no link"), False),
            ("phone", self._message(text="x", entities=[entity("phone_number")]), True),
            ("phone", self._message(text="555"), False),
            ("email", self._message(caption="a@b.co", caption_entities=[entity("email")]), True),
            ("command", self._message(text="/lock url"), True),
            ("command", self._message(text="lock url"), False),
            ("forward", self._message(forward_date=1), True),
            ("forward", self._message(text="x"), False),
            ("videonote", self._message(video_note=1), True),
            ("videonote", self._message(video=1), False),
            ("egame", self._message(dice=1), True),
            ("emojicustom", self._message(text="x", entities=[entity("custom_emoji")]), True),
            (
                "stickerpremium",
                self._message(sticker=SimpleNamespace(premium=True)),
                True,
            ),
            (
                "stickerpremium",
                self._message(sticker=SimpleNamespace(premium=False)),
                False,
            ),
            (
                "stickeranimated",
                self._message(sticker=SimpleNamespace(is_animated=True)),
                True,
            ),
            (
                "stickeranimated",
                self._message(sticker=SimpleNamespace(is_animated=False)),
                False,
            ),
        ]
        for name, message, expected in cases:
            with self.subTest(lock=name):
                self.assertEqual(bool(locks[name](message)), expected)

    def test_manually_handled_locks_are_not_predicates(self):
        # These have dedicated branches in del_lockables and must not be called.
        for name in ("bots", "rtl", "button", "inline", "anonchannel",
                     "forwardchannel", "forwardbot"):
            with self.subTest(lock=name):
                self.assertIsInstance(self._locks()[name], str)


class HandlerChainingTests(unittest.TestCase):
    """chain() reproduces PTB's block=False. aiogram's observer.trigger() returns
    after the first matching handler, so 105 handlers that used to share a
    message with the ones after them would otherwise never run."""

    @staticmethod
    def _message():
        from datetime import datetime

        from aiogram.types import Chat, Message, User

        return Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="x"),
            text="/cmd",
        )

    def _router_with(self, handlers):
        from aiogram import Router

        router = Router()
        for handler, filters in handlers:
            router.message.register(handler, *filters)
        return router

    def test_chained_handlers_all_run(self):
        from Mikobot.utils.gate import chain

        calls = []

        async def first(message):
            calls.append("first")

        async def second(message):
            calls.append("second")

        router = self._router_with([(chain(first), ()), (chain(second), ())])
        asyncio.run(router.propagate_event("message", self._message()))
        self.assertEqual(calls, ["first", "second"])

    def test_unchained_handler_stops_propagation(self):
        from Mikobot.utils.gate import chain

        calls = []

        async def solo(message):
            calls.append("solo")
            return "handled"

        async def never(message):
            calls.append("never")

        router = self._router_with([(solo, ()), (chain(never), ())])
        result = asyncio.run(router.propagate_event("message", self._message()))
        self.assertEqual(calls, ["solo"])
        self.assertEqual(result, "handled")

    def test_chain_is_idempotent(self):
        from Mikobot.utils.gate import chain

        async def handler(message):
            return None

        once = chain(handler)
        self.assertIs(chain(once), once)


class GateMiddlewareTests(unittest.TestCase):
    """The gate replaces PTB decorator wrappers. aiogram injects handler arguments
    by name from the inner signature, so the wrappers had to become tags on the
    handler plus one middleware; this pins the behaviour those wrappers had."""

    def _middleware(self):
        from Mikobot.plugins.helper_funcs import chat_status
        from Mikobot.utils.gate import GateMiddleware

        self.status = chat_status
        return GateMiddleware(chat_status)

    def _event(self, chat_type="supergroup", user_id=5, text="/cmd"):
        event = SimpleNamespace(
            chat=SimpleNamespace(id=-100, type=chat_type),
            from_user=SimpleNamespace(id=user_id),
            text=text,
        )
        event.replies = []
        event.deleted = False

        async def answer(text, **kwargs):
            event.replies.append(text)

        async def delete():
            event.deleted = True

        event.answer = answer
        event.delete = delete
        return event

    def _bot(self, members):
        bot = SimpleNamespace(id=1)
        bot.actions = []

        async def get_chat_member(chat_id, user_id):
            return members.get(user_id)

        async def send_chat_action(chat_id, action):
            bot.actions.append(action)

        bot.get_chat_member = get_chat_member
        bot.send_chat_action = send_chat_action
        return bot

    @staticmethod
    async def _handler(event, data):
        return "HANDLED"

    def _run(self, callback, event, bot):
        middleware = self._middleware()
        # aiogram passes the HandlerObject under "handler" (see
        # TelegramEventObserver.trigger), not "event_handler".
        data = {"bot": bot, "handler": SimpleNamespace(callback=callback)}
        return asyncio.run(middleware(self._handler, event, data))

    def test_outermost_decorator_runs_first(self):
        from Mikobot.plugins.helper_funcs import alternate, chat_status

        @chat_status.check_admin(is_user=True)
        @alternate.typing_action
        async def cmd(message):
            return None

        self.assertEqual(
            [spec.get("kind") or spec.get("chat_action") for spec in cmd.requirements],
            ["admin", "typing"],
        )

    def test_non_admin_is_stopped_before_the_handler(self):
        from Mikobot.plugins.helper_funcs import alternate, chat_status

        @chat_status.check_admin(is_user=True)
        @alternate.typing_action
        async def cmd(message):
            return None

        event = self._event()
        bot = self._bot({5: SimpleNamespace(status="member", user=SimpleNamespace(id=5))})
        self.assertIsNone(self._run(cmd, event, bot))
        self.assertEqual(event.replies, ["You are not admin here."])

    def test_admin_passes_and_the_chat_action_fires(self):
        from Mikobot.plugins.helper_funcs import alternate, chat_status

        @chat_status.check_admin(is_user=True)
        @alternate.typing_action
        async def cmd(message):
            return None

        event = self._event()
        bot = self._bot({5: SimpleNamespace(status="administrator", user=SimpleNamespace(id=5))})
        self.assertEqual(self._run(cmd, event, bot), "HANDLED")
        self.assertEqual(event.replies, [])
        self.assertEqual(bot.actions, ["typing"])

    def test_private_chat_skips_the_permission_gate(self):
        from Mikobot.plugins.helper_funcs import chat_status

        @chat_status.check_admin(is_user=True)
        async def cmd(message):
            return None

        event = self._event(chat_type="private")
        bot = self._bot({})
        self.assertEqual(self._run(cmd, event, bot), "HANDLED")
        self.assertEqual(event.replies, [])

    def test_dev_plus_denies_an_ordinary_user(self):
        from Mikobot.plugins.helper_funcs import chat_status

        with mock.patch.object(chat_status, "DEV_USERS", [7]), mock.patch.object(
            chat_status, "DEL_CMDS", False
        ):

            @chat_status.dev_plus
            async def cmd(message):
                return None

            event = self._event()
            bot = self._bot({})
            self.assertIsNone(self._run(cmd, event, bot))
            self.assertEqual(
                event.replies,
                [
                    "This is a developer restricted command. "
                    "You do not have permissions to run this."
                ],
            )

    def test_dev_plus_allows_a_dev(self):
        from Mikobot.plugins.helper_funcs import chat_status

        with mock.patch.object(chat_status, "DEV_USERS", [7]), mock.patch.object(
            chat_status, "DRAGONS", [7]
        ):

            @chat_status.dev_plus
            async def cmd(message):
                return None

            event = self._event(user_id=7)
            self.assertEqual(self._run(cmd, event, self._bot({})), "HANDLED")


class EnvIntegerParsingTests(unittest.TestCase):
    """int(None) raises TypeError, which an `except ValueError` never catches, so a
    missing variable used to escape as a raw traceback instead of a clear message."""

    def _env_int(self, environ, name, default=None):
        source = (ROOT / "Mikobot/__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "env_int"
        )
        module = ast.Module(body=[function], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {"os": SimpleNamespace(environ=environ)}
        exec(compile(module, "env_int.py", "exec"), namespace)
        return namespace["env_int"](name, default)

    def test_missing_value_reports_a_clear_error(self):
        with self.assertRaises(SystemExit) as caught:
            self._env_int({}, "OWNER_ID")
        self.assertIn("OWNER_ID", str(caught.exception))

    def test_non_numeric_value_reports_a_clear_error(self):
        with self.assertRaises(SystemExit):
            self._env_int({"OWNER_ID": "not-a-number"}, "OWNER_ID")

    def test_valid_value_is_parsed(self):
        self.assertEqual(self._env_int({"OWNER_ID": "42"}, "OWNER_ID"), 42)

    def test_default_is_used_when_absent(self):
        self.assertEqual(self._env_int({}, "SUPPORT_ID", -100), -100)


class ExtractTimeTests(unittest.TestCase):
    """extract_time feeds until_date, which aiogram strictly validates."""

    def _reply_texts(self):
        replies = []

        class _Message:
            async def reply_text(self, text, *args, **kwargs):
                replies.append(text)

        return _Message(), replies

    def test_valid_durations_return_an_absolute_expiry(self):
        import time

        from Mikobot.plugins.helper_funcs.string_handling import extract_time

        message, replies = self._reply_texts()
        for value, seconds in (("30m", 1800), ("2h", 7200), ("1d", 86400)):
            before = int(time.time())
            result = asyncio.run(extract_time(message, value))
            self.assertIsInstance(result, int, value)
            self.assertGreaterEqual(result, before + seconds)
        self.assertEqual(replies, [])

    def test_malformed_input_returns_none_not_a_sentinel_string(self):
        # PTB tolerated "" here; aiogram rejects it as until_date, and
        # None would mean a permanent ban, so callers guard on falsiness.
        from Mikobot.plugins.helper_funcs.string_handling import extract_time

        for value in ("abcm", "10x", "", "m"):
            message, replies = self._reply_texts()
            result = asyncio.run(extract_time(message, value))
            self.assertIsNone(result, value)

    def test_returned_value_is_accepted_by_aiogram_until_date(self):
        from aiogram.methods import BanChatMember

        from Mikobot.plugins.helper_funcs.string_handling import extract_time

        for value in ("10m", "not-a-duration"):
            message, _ = self._reply_texts()
            expiry = asyncio.run(extract_time(message, value))
            if expiry:
                # Only the success path reaches the API; the failure path
                # must be skipped by the caller's guard.
                BanChatMember(chat_id=1, user_id=2, until_date=expiry)

    def test_every_caller_guards_the_result_before_using_it(self):
        # A ban with until_date=None is permanent, so an unguarded caller
        # turns a typo'd duration into an indefinite punishment.
        bad = []
        for path in sorted((ROOT / "Mikobot").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Await)):
                    continue
                call = node.value.value
                if not (
                    isinstance(call, ast.Call) and getattr(call.func, "id", "") == "extract_time"
                ):
                    continue
                name = node.targets[0].id
                guarded = any(
                    isinstance(n, ast.If)
                    and isinstance(n.test, ast.UnaryOp)
                    and isinstance(n.test.op, ast.Not)
                    and isinstance(n.test.operand, ast.Name)
                    and n.test.operand.id == name
                    for n in ast.walk(tree)
                )
                if not guarded:
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
        self.assertEqual(bad, [])


class BotIdentityFallbackTests(unittest.TestCase):
    """A failed getMe must not be cached as a permanent identity."""

    def _fresh_module(self):
        """Import Mikobot without reaching the real Telegram API.

        Importing Mikobot pulls in Database/sql, which reads BOT_ID and so
        fires a getMe at import time. A deliberately invalid token makes
        that call fail fast and locally instead of authenticating.
        """
        import importlib
        import os
        import sys

        module = sys.modules.get("Mikobot")
        if module is None:
            saved_env = os.environ.get("TOKEN")
            os.environ["TOKEN"] = "0000000000:TESTTOKENPLACEHOLDERnotarealtoken"
            self.addCleanup(
                lambda: os.environ.__setitem__("TOKEN", saved_env)
                if saved_env is not None
                else os.environ.pop("TOKEN", None)
            )
            try:
                module = importlib.import_module("Mikobot")
            except Exception:
                return None, None, None, None
        saved = {k: getattr(module, k) for k in ("_BOT_INFO", "bot", "loop")}
        calls = {"count": 0}

        class _User:
            id, first_name, username = 42, "Name", "name_bot"

        class _StubBot:
            def __init__(self, fail):
                self._fail = fail

            async def me(self):
                calls["count"] += 1
                if self._fail:
                    raise RuntimeError("network down")
                return _User()

        class _Loop:
            """A real event loop, so the coroutine actually runs."""

            def __init__(self):
                import asyncio

                self._loop = asyncio.new_event_loop()

            def run_until_complete(self, coro):
                return self._loop.run_until_complete(coro)

        if saved is not None:
            module._BOT_INFO = None
            module.bot = _StubBot(fail=True)
            module.loop = _Loop()
        self.addCleanup(self._restore, module, saved)
        return module, _StubBot, _User, calls

    @staticmethod
    def _restore(module, saved):
        if module is None or saved is None:
            return
        for key, value in saved.items():
            setattr(module, key, value)

    def test_a_failed_fetch_is_not_cached(self):
        # BOT_ID=0 makes the admin-list check fail for everyone and writes a
        # junk users row, so a transient timeout must be retried later.
        module, stub_bot, user_cls, calls = self._fresh_module()
        if module is None:
            self.skipTest("Mikobot is not importable")

        self.assertEqual(module.fetch_bot_info(), (0, "Bot", ""))
        self.assertIsNone(module._BOT_INFO, "placeholder was cached")

        # A later attempt must be able to succeed and take over the identity.
        module.bot = stub_bot(fail=False)
        self.assertEqual(module.fetch_bot_info(), (42, "Name", "name_bot"))
        self.assertEqual(module._BOT_INFO, (42, "Name", "name_bot"))
        self.assertEqual(calls["count"], 2)

    def test_a_successful_fetch_is_cached(self):
        module, stub_bot, user_cls, calls = self._fresh_module()
        if module is None:
            self.skipTest("Mikobot is not importable")

        module.bot = stub_bot(fail=False)
        self.assertEqual(module.fetch_bot_info(), (42, "Name", "name_bot"))
        self.assertEqual(module.fetch_bot_info(), (42, "Name", "name_bot"))
        self.assertEqual(calls["count"], 1, "a resolved identity should not be re-fetched")


class GateMiddlewareHandlerKeyTests(unittest.TestCase):
    """The gate middleware must read the key aiogram actually provides.

    It is registered on every observer, so reading a key aiogram does not
    supply made every inbound update raise KeyError and silently do nothing.
    """

    def _middleware(self):
        from Mikobot.utils.gate import GateMiddleware

        class _Status:
            DEV_USERS = frozenset()

            def is_sudo_plus(self, chat, uid):
                return False

            def is_support_plus(self, chat, uid):
                return False

            def is_whitelist_plus(self, chat, uid):
                return False

            async def is_user_admin(self, chat, uid):
                return False

        return GateMiddleware(_Status())

    def test_middleware_reads_the_handler_object_aiogram_passes(self):
        import asyncio

        from aiogram.dispatcher.event.handler import HandlerObject

        from Mikobot import bot

        ran = []

        async def handler(update, data=None):
            ran.append(update)
            return "handled"

        handler_obj = HandlerObject(callback=handler)
        event = object()
        # Exactly the keys aiogram builds before calling outer middlewares.
        data = {"bot": bot, "handler": handler_obj}

        # aiogram passes HandlerObject.call as the downstream handler.
        result = asyncio.run(self._middleware()(handler_obj.call, event, data))
        self.assertEqual(result, "handled")
        self.assertEqual(ran, [event])

    def test_aiogram_never_supplies_an_event_handler_key(self):
        import inspect

        from aiogram.dispatcher.event.telegram import TelegramEventObserver

        source = inspect.getsource(TelegramEventObserver)
        self.assertIn('kwargs["handler"]', source)
        # Guards against someone renaming the key the middleware relies on.
        source_gate = inspect.getsource(
            __import__("Mikobot.utils.gate", fromlist=["x"])
        )
        self.assertNotIn('data["event_handler"]', source_gate)
        self.assertIn('data["handler"]', source_gate)


if __name__ == "__main__":
    unittest.main()