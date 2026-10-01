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
            """Only needed for error_callback's annotation."""

        # aiogram passes an ErrorEvent, which carries .update and .exception;
        # it has no .event.
        class ErrorEvent:
            def __init__(self):
                self.update = CallbackQuery()
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

        await error_callback(ErrorEvent())
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers[0][1]["show_alert"])
        self.assertEqual(len(warnings), 1)

    def test_loggable_forwards_every_injected_argument(self):
        # The wrapper used to declare `message` itself, so aiogram's injected
        # arguments (e.g. `command`) were dropped and 36 command handlers
        # raised TypeError instead of running.
        from datetime import datetime as _dt

        from aiogram.types import Chat, Message

        sent = []

        async def send_log(log_chat_id, orig_chat_id, result):
            sent.append(result)

        namespace = {
            "wraps": __import__("functools").wraps,
            "ChatType": SimpleNamespace(SUPERGROUP="supergroup"),
            "Message": Message,
            "send_log": send_log,
            "sql": SimpleNamespace(get_chat_log_channel=lambda chat_id: -100),
            "LOGGER": SimpleNamespace(exception=lambda *args, **kwargs: None),
            "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
        }
        source = ROOT / "Mikobot/plugins/log_channel.py"
        load_nested_function(source, "_event_message", namespace)
        loggable = load_nested_function(source, "loggable", namespace)

        seen = {}

        @loggable
        async def action(message, command):
            seen["command"] = command
            return "event"

        message = Message(
            message_id=1, date=_dt.now(), chat=Chat(id=42, type="private"), text="/cmd"
        )
        sentinel = object()
        result = asyncio.run(action(message, command=sentinel))
        self.assertEqual(seen["command"], sentinel)
        # loggable appends the event stamp before returning.
        self.assertTrue(result.startswith("event\nEvent stamp:"))
        self.assertTrue(sent and sent[0].startswith("event\nEvent stamp:"))

    async def test_audit_log_failure_does_not_fail_successful_action(self):
        async def failing_send_log(*args, **kwargs):
            raise RuntimeError("log delivery failed")

        async def successful_action(message):
            return "event"

        from aiogram.types import Chat, Message
        from datetime import datetime as _dt

        namespace = {
            "wraps": __import__("functools").wraps,
            "ChatType": SimpleNamespace(SUPERGROUP="supergroup"),
            "Message": Message,
            "send_log": failing_send_log,
            "sql": SimpleNamespace(get_chat_log_channel=lambda chat_id: -100),
            "LOGGER": SimpleNamespace(exception=lambda *args, **kwargs: None),
            "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
        }
        source = ROOT / "Mikobot/plugins/log_channel.py"
        # loggable resolves _event_message, so both have to be in scope.
        load_nested_function(source, "_event_message", namespace)
        loggable = load_nested_function(source, "loggable", namespace)
        message = Message(
            message_id=1,
            date=_dt.now(),
            chat=Chat(id=42, type="private"),
            text="/cmd",
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

        main_source = (ROOT / "Mikobot/__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("markdownhelp", main_source)

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
        self.assertIn("MenuButtonWebApp(\n                text=args[1],\n                web_app=WebAppInfo(url=args[1]),", chatadmin)
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

    def test_a_failing_chained_handler_still_raises(self):
        # SkipHandler must not be raised from a finally block: that replaced
        # the in-flight exception, so failures in 150 chained handlers were
        # invisible to error_callback.
        import asyncio

        from Mikobot.utils.gate import chain

        @chain
        async def boom(message):
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            asyncio.run(boom(None))

    def test_a_successful_chained_handler_continues_the_chain(self):
        import asyncio

        from aiogram.dispatcher.event.bases import SkipHandler

        from Mikobot.utils.gate import chain

        @chain
        async def fine(message):
            return "ok"

        with self.assertRaises(SkipHandler):
            asyncio.run(fine(None))

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

    def _patched_is_admin(self, is_admin: bool):
        """Stub chat_status.is_user_admin, which otherwise uses the real bot."""
        from contextlib import contextmanager

        from Mikobot.plugins.helper_funcs import chat_status

        @contextmanager
        def patcher():
            original = chat_status.is_user_admin

            async def fake(chat, user_id, member=None):
                return is_admin

            chat_status.is_user_admin = fake
            try:
                yield
            finally:
                chat_status.is_user_admin = original

        return patcher()

    def test_user_not_admin_skips_quietly_for_an_admin(self):
        # PTB only reached the handler when the sender was not an admin; the
        # gate returned None from both paths, so admins were not protected.
        from Mikobot.plugins.helper_funcs import chat_status

        @chat_status.user_not_admin
        async def cmd(message):
            return None

        event = self._event()
        bot = self._bot({5: SimpleNamespace(status="administrator", user=SimpleNamespace(id=5))})
        with self._patched_is_admin(True):
            self.assertIsNone(self._run(cmd, event, bot))
        self.assertEqual(event.replies, [])
        self.assertFalse(event.deleted)

    def test_user_not_admin_runs_for_an_ordinary_user(self):
        from Mikobot.plugins.helper_funcs import chat_status

        @chat_status.user_not_admin
        async def cmd(message):
            return None

        event = self._event()
        bot = self._bot({5: SimpleNamespace(status="member", user=SimpleNamespace(id=5))})
        with self._patched_is_admin(False):
            self.assertEqual(self._run(cmd, event, bot), "HANDLED")
        self.assertEqual(event.replies, [])

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


class SqlLayerDatabaseTests(unittest.TestCase):
    """Execute the SQL layer against a real PostgreSQL when one is available.

    The rest of this file only reads Database/sql sources as text, so nothing
    here would catch a broken column type or a query that no longer matches
    the schema. Skipped when no database is configured or reachable.
    """

    UID = 900000001
    CID = -100900000001

    @classmethod
    def setUpClass(cls):
        import os
        import socket
        from urllib.parse import urlparse

        url = os.environ.get("DATABASE_URL")
        if not url:
            raise unittest.SkipTest("DATABASE_URL is not set")
        host = urlparse(url).hostname
        if host:
            try:
                socket.getaddrinfo(host, None)
            except socket.gaierror:
                raise unittest.SkipTest(f"database host {host} does not resolve")

        import importlib
        import pkgutil
        import sys

        sys.path.insert(0, str(ROOT))
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("sqlalchemy is not installed")

        import Database.sql as dbsql

        for module in pkgutil.iter_modules(dbsql.__path__):
            if module.name.endswith("_sql"):
                importlib.import_module(f"Database.sql.{module.name}")
        try:
            from Database.sql import start
        except Exception as error:  # pragma: no cover - environment specific
            raise unittest.SkipTest(f"cannot open the database: {error}")
        # staticmethod keeps this a plain function; a bare assignment would
        # bind it as a method and start() takes no arguments.
        cls._start = staticmethod(start)

    def setUp(self):
        try:
            self._start()
        except Exception as error:
            self.skipTest(f"cannot open the database: {error}")
        self._clear_probe_state()

    def _clear_probe_state(self):
        # These helpers are not idempotent (approve inserts unconditionally),
        # so a rerun against the same database would trip the primary key.
        from Database.sql import approve_sql, blacklist_sql, disable_sql, warns_sql

        for call in (
            lambda: approve_sql.disapprove(self.CID, self.UID),
            lambda: blacklist_sql.rm_from_blacklist(self.CID, "sql_layer_probe"),
            lambda: disable_sql.enable_command(self.CID, "sql_layer_probe"),
            warns_sql.reset_warns(self.UID, self.CID),
        ):
            try:
                call()
            except Exception:
                pass  # nothing to remove on a first run

    def test_warns_round_trips_through_the_array_column(self):
        from Database.sql import warns_sql

        warns_sql.reset_warns(self.UID, self.CID)
        warns_sql.warn_user(self.UID, self.CID, "first")
        warns_sql.warn_user(self.UID, self.CID, "second")
        count, reasons = warns_sql.get_warns(self.UID, self.CID)
        self.assertEqual(count, 2)
        self.assertEqual(set(reasons), {"first", "second"})
        self.assertTrue(warns_sql.remove_warn(self.UID, self.CID))
        warns_sql.reset_warns(self.UID, self.CID)

    def test_ensure_bot_in_db_is_idempotent(self):
        # Startup calls this on every boot; a second call must not duplicate.
        from Database.sql import users_sql

        users_sql.ensure_bot_in_db()
        users_sql.ensure_bot_in_db()
        # merge() keyed on the user id, so one row survives both calls.
        from Mikobot import BOT_ID

        self.assertIsNotNone(users_sql.get_name_by_userid(BOT_ID))

    def test_user_round_trip(self):
        from Database.sql import users_sql

        users_sql.update_user(self.UID, "sql_layer_probe")
        self.assertEqual(users_sql.get_name_by_userid(self.UID).username, "sql_layer_probe")

    def test_blacklist_round_trip(self):
        from Database.sql import blacklist_sql

        blacklist_sql.add_to_blacklist(self.CID, "sql_layer_probe")
        self.assertIn("sql_layer_probe", blacklist_sql.get_chat_blacklist(self.CID))
        self.assertTrue(blacklist_sql.rm_from_blacklist(self.CID, "sql_layer_probe"))
        self.assertNotIn("sql_layer_probe", blacklist_sql.get_chat_blacklist(self.CID))

    def test_disabled_command_round_trip(self):
        from Database.sql import disable_sql

        disable_sql.disable_command(self.CID, "sql_layer_probe")
        self.assertTrue(disable_sql.is_command_disabled(self.CID, "sql_layer_probe"))
        self.assertTrue(disable_sql.enable_command(self.CID, "sql_layer_probe"))
        self.assertFalse(disable_sql.is_command_disabled(self.CID, "sql_layer_probe"))

    def test_lock_and_restriction_round_trip(self):
        from Database.sql import locks_sql

        locks_sql.update_lock(self.CID, "sticker", True)
        # is_locked returns False, not None, when the chat is not locked.
        self.assertTrue(locks_sql.is_locked(self.CID, "sticker"))
        # update_restriction only handles these types; "sticker" is a lock,
        # not a restriction, and would silently do nothing.
        locks_sql.update_restriction(self.CID, "messages", True)
        self.assertTrue(locks_sql.is_restr_locked(self.CID, "messages"))

    def test_approval_round_trip(self):
        from Database.sql import approve_sql

        approve_sql.approve(self.CID, self.UID)
        self.assertIsNotNone(approve_sql.is_approved(self.CID, self.UID))
        # list_approved returns ORM rows, not bare ids.
        self.assertIn(self.UID, [row.user_id for row in approve_sql.list_approved(self.CID)])
        self.assertTrue(approve_sql.disapprove(self.CID, self.UID))
        self.assertIsNone(approve_sql.is_approved(self.CID, self.UID))


class AiogramModelKeywordTests(unittest.TestCase):
    """aiogram's pydantic models take keyword arguments only.

    A positional first argument raises TypeError at construction, so every
    inline keyboard in the bot was unbuildable.
    """

    NAMES = (
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "InputTextMessageContent",
        "KeyboardButton",
        "ReplyKeyboardMarkup",
        "ReplyKeyboardRemove",
        "ForceReply",
        "ChatPermissions",
        "LinkPreviewOptions",
        "InlineQueryResultArticle",
    )

    def test_no_aiogram_model_is_built_with_a_positional_argument(self):
        # Subclasses count too: EqInlineKeyboardButton subclasses
        # InlineKeyboardButton to give it value equality, and a positional
        # call on it failed the same way.
        names = set(self.NAMES)
        for path in sorted((ROOT / "Mikobot").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(b, ast.Name) and b.id in names for b in node.bases
                ):
                    names.add(node.name)

        bad = []
        for path in sorted((ROOT / "Mikobot").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in names
                ):
                    continue
                if node.args:
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.func.id}")
        self.assertEqual(bad, [])

    def test_keyword_construction_works(self):
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="x", callback_data="y")]]
        )
        self.assertEqual(markup.inline_keyboard[0][0].text, "x")

    def test_command_args_is_none_without_arguments(self):
        # PTB handed over []; aiogram hands over None, so len()/indexing must
        # be guarded or normalised at the extraction point.
        try:
            from aiogram.filters.command import CommandObject
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        self.assertIsNone(CommandObject(prefix="/", command="start", args=None).args)

    def test_error_event_exposes_update_not_event(self):
        try:
            from aiogram.types import ErrorEvent
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        self.assertIn("update", ErrorEvent.model_fields)
        self.assertNotIn("event", ErrorEvent.model_fields)


class UnresolvedTargetTests(unittest.TestCase):
    """An unresolvable target must not reach a Bot API call as None.

    extract_user* return None when the username is unknown. PTB sent that to
    Telegram and caught the API error; aiogram validates the argument
    client-side and raises ValidationError, which is not a TelegramAPIError,
    so it escaped the handlers' except clauses.
    """

    def test_ban_guards_a_none_target(self):
        import ast

        source = (ROOT / "Mikobot/plugins/ban.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        guarded = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            body = ast.unparse(node)
            if "extract_user_and_text" not in body:
                continue
            if "if user_id is None:" in body:
                guarded += 1
        self.assertEqual(guarded, 4, "every ban-family handler must guard a None target")

    def test_aiogram_rejects_a_none_user_id(self):
        try:
            from aiogram.methods import GetChatMember
        except ModuleNotFoundError:
            self.skipTest("aiogram is not installed")

        with self.assertRaises(Exception):
            GetChatMember(chat_id=1, user_id=None)


class PluginModNameTests(unittest.TestCase):
    """Two plugins must never claim the same __mod_name__.

    Mikobot/__main__.py aborts the whole bot with "Can't have two modules with
    the same name!" on a duplicate, so a collision is a total startup failure,
    not a degraded feature. It took production down once already.
    """

    def _mod_names(self):
        import ast

        names = {}
        for path in sorted((ROOT / "Mikobot/plugins").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                # Class-scoped __mod_name__ is legal and is not loader-visible.
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__mod_name__":
                        if isinstance(node.value, ast.Constant):
                            names.setdefault(
                                node.value.value.lower(), []
                            ).append(path.name)
        return names

    def test_no_duplicate_mod_names(self):
        names = self._mod_names()
        duplicates = {
            name: owners for name, owners in names.items() if len(owners) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "duplicate __mod_name__ would abort startup in Mikobot/__main__.py",
        )


class MentionHelperTests(unittest.TestCase):
    """mention_html/mention_markdown are interpolated into log and chat text.

    The aiogram port dropped the `await` and transposed the arguments, so every
    call site rendered `<coroutine object mention_html at 0x...>` into the log
    channel instead of a mention. The helpers are synchronous and id-first, and
    the caller passes the raw name because the helper escapes it.
    """

    def test_helpers_are_synchronous_and_id_first(self):
        parser = ROOT / "Mikobot/utils/parser.py"
        tree = ast.parse(parser.read_text(encoding="utf-8"))
        found = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
                "mention_html",
                "mention_markdown",
            ):
                found[node.name] = node
        self.assertEqual(
            sorted(found), ["mention_html", "mention_markdown"], "both helpers must exist"
        )
        for name, node in found.items():
            self.assertNotIsInstance(
                node,
                ast.AsyncFunctionDef,
                f"{name} is interpolated, never awaited; it must stay synchronous",
            )
            self.assertEqual(
                [arg.arg for arg in node.args.args],
                ["user_id", "name"],
                f"{name} must take the id first",
            )

    def test_escaping_happens_once_inside_the_helper(self):
        from Mikobot.utils import parser

        # Escaped exactly once: a raw name with markup becomes a mention whose
        # label is escaped, not double-escaped.
        self.assertEqual(
            parser.mention_html(7, "Al<ice"),
            '<a href="tg://user?id=7">Al&lt;ice</a>',
        )
        self.assertEqual(
            parser.mention_markdown(7, "Al*ice"),
            "[Al\\*ice](tg://user?id=7)",
        )

    def test_no_call_site_awaits_or_double_escapes(self):
        offenders = []
        for path in sorted(ROOT.glob("Mikobot/**/*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            awaited = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id not in ("mention_html", "mention_markdown"):
                    continue
                if len(node.args) != 2:
                    continue
                if id(node) in awaited:
                    offenders.append(f"{path.name}:{node.lineno} is awaited")
                name_arg = node.args[1]
                if isinstance(name_arg, ast.Call) and ast.unparse(name_arg.func) in (
                    "escape",
                    "html.escape",
                    "escape_markdown",
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno} pre-escapes; the helper already does"
                    )
        self.assertEqual(
            offenders,
            [],
            "mention helpers are sync and escape internally; call sites must not "
            "await them or escape the name again",
        )

    def test_no_call_site_is_left_unawaited_by_a_reintroduced_async_helper(self):
        """An async helper can never be interpolated, so catch the regression shape."""
        parser = (ROOT / "Mikobot/utils/parser.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "async def mention_html", parser, "the mention helpers must not become async"
        )
        self.assertNotIn("async def mention_markdown", parser)


    def test_warn_action_in_blacklists_is_awaited(self):
        """warn() is a coroutine, so an un-awaited call drops the moderation action.

        Both blacklist plugins used a bare `warn(...)`, which builds a coroutine and
        throws it away: the trigger was deleted but the user was never warned, never
        recorded, and never banned at the limit.
        """
        for relative in (
            "Mikobot/plugins/blacklist.py",
            "Mikobot/plugins/blacklist_stickers.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            awaited = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
            }
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "warn"
            ]
            self.assertTrue(calls, f"{relative} should still call warn()")
            for call in calls:
                self.assertIn(
                    id(call),
                    awaited,
                    f"{relative}:{call.lineno} must await warn()",
                )


class UnescapedOutputTests(unittest.TestCase):
    """Display names and chat titles are attacker-controlled.

    Telegram lets any user pick a first_name and any admin rename a group, and
    both are interpolated straight into replies. The bot's default parse_mode is
    HTML, so an unescaped value containing <b> or & renders as markup instead of
    text, which lets a name masquerade in a moderation notice. Every site has to
    escape for the parse mode it actually sends with.
    """

    _FIELDS = ("first_name", "last_name", "title")

    def _unescaped_sites(self):
        sites = []
        for path in sorted(ROOT.glob("Mikobot/**/*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else ""
                if name not in (
                    "send_message",
                    "answer",
                    "reply_text",
                    "reply",
                    "edit_text",
                ):
                    continue
                body = ast.unparse(node)
                if "escape" in body or "mention_html" in body:
                    continue
                for field in self._FIELDS:
                    pattern = r"\{[^}]*\." + field + r"\b[^}]*\}"
                    if re.search(pattern, body):
                        sites.append(f"{path.name}:{node.lineno} raw .{field}")
                        break
        return sites

    def test_no_display_name_or_title_is_interpolated_raw(self):
        self.assertEqual(
            self._unescaped_sites(),
            [],
            "escape first_name/last_name/title for the parse mode being sent, "
            "or route the value through mention_html()",
        )

    def test_escaping_actually_neutralises_markup(self):
        import html as html_module

        from Mikobot.utils.parser import escape_markdown

        name = 'Al<b>BOLD</b>&"q"'
        escaped = html_module.escape(name)
        self.assertNotIn("<b>", escaped)
        self.assertIn("&lt;b&gt;", escaped)

        # legacy Markdown only honours * _ ` [, and escape_markdown backslashes all four
        marked = "Al*b*_x`y[z]"
        out = escape_markdown(marked)
        active = [
            char
            for index, char in enumerate(out)
            if char in "*_`[" and (index == 0 or out[index - 1] != "\\")
        ]
        self.assertEqual(active, [], f"markdown metachars left active: {active}")


class PluginModNameTests(unittest.TestCase):
    """Two plugins must never claim the same __mod_name__.

    Mikobot/__main__.py aborts the whole bot with "Can't have two modules with
    the same name!" on a duplicate, so a collision is a total startup failure,
    not a degraded feature. It took production down once already.
    """

    def _mod_names(self):
        import ast

        names = {}
        for path in sorted((ROOT / "Mikobot/plugins").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                # Class-scoped __mod_name__ is legal and is not loader-visible.
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__mod_name__":
                        if isinstance(node.value, ast.Constant):
                            names.setdefault(
                                node.value.value.lower(), []
                            ).append(path.name)
        return names

    def test_no_duplicate_mod_names(self):
        names = self._mod_names()
        duplicates = {
            name: owners for name, owners in names.items() if len(owners) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "duplicate __mod_name__ would abort startup in Mikobot/__main__.py",
        )


class MentionHelperTests(unittest.TestCase):
    """mention_html/mention_markdown are interpolated into log and chat text.

    The aiogram port dropped the `await` and transposed the arguments, so every
    call site rendered `<coroutine object mention_html at 0x...>` into the log
    channel instead of a mention. The helpers are synchronous and id-first, and
    the caller passes the raw name because the helper escapes it.
    """

    def test_helpers_are_synchronous_and_id_first(self):
        parser = ROOT / "Mikobot/utils/parser.py"
        tree = ast.parse(parser.read_text(encoding="utf-8"))
        found = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
                "mention_html",
                "mention_markdown",
            ):
                found[node.name] = node
        self.assertEqual(
            sorted(found), ["mention_html", "mention_markdown"], "both helpers must exist"
        )
        for name, node in found.items():
            self.assertNotIsInstance(
                node,
                ast.AsyncFunctionDef,
                f"{name} is interpolated, never awaited; it must stay synchronous",
            )
            self.assertEqual(
                [arg.arg for arg in node.args.args],
                ["user_id", "name"],
                f"{name} must take the id first",
            )

    def test_escaping_happens_once_inside_the_helper(self):
        from Mikobot.utils import parser

        # Escaped exactly once: a raw name with markup becomes a mention whose
        # label is escaped, not double-escaped.
        self.assertEqual(
            parser.mention_html(7, "Al<ice"),
            '<a href="tg://user?id=7">Al&lt;ice</a>',
        )
        self.assertEqual(
            parser.mention_markdown(7, "Al*ice"),
            "[Al\\*ice](tg://user?id=7)",
        )

    def test_no_call_site_awaits_or_double_escapes(self):
        offenders = []
        for path in sorted(ROOT.glob("Mikobot/**/*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            awaited = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id not in ("mention_html", "mention_markdown"):
                    continue
                if len(node.args) != 2:
                    continue
                if id(node) in awaited:
                    offenders.append(f"{path.name}:{node.lineno} is awaited")
                name_arg = node.args[1]
                if isinstance(name_arg, ast.Call) and ast.unparse(name_arg.func) in (
                    "escape",
                    "html.escape",
                    "escape_markdown",
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno} pre-escapes; the helper already does"
                    )
        self.assertEqual(
            offenders,
            [],
            "mention helpers are sync and escape internally; call sites must not "
            "await them or escape the name again",
        )

    def test_no_call_site_is_left_unawaited_by_a_reintroduced_async_helper(self):
        """An async helper can never be interpolated, so catch the regression shape."""
        parser = (ROOT / "Mikobot/utils/parser.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "async def mention_html", parser, "the mention helpers must not become async"
        )
        self.assertNotIn("async def mention_markdown", parser)


    def test_warn_action_in_blacklists_is_awaited(self):
        """warn() is a coroutine, so an un-awaited call drops the moderation action.

        Both blacklist plugins used a bare `warn(...)`, which builds a coroutine and
        throws it away: the trigger was deleted but the user was never warned, never
        recorded, and never banned at the limit.
        """
        for relative in (
            "Mikobot/plugins/blacklist.py",
            "Mikobot/plugins/blacklist_stickers.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            awaited = {
                id(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
            }
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "warn"
            ]
            self.assertTrue(calls, f"{relative} should still call warn()")
            for call in calls:
                self.assertIn(
                    id(call),
                    awaited,
                    f"{relative}:{call.lineno} must await warn()",
                )


class PluginModNameTests(unittest.TestCase):
    """Two plugins must never claim the same __mod_name__.

    Mikobot/__main__.py aborts the whole bot with "Can't have two modules with
    the same name!" on a duplicate, so a collision is a total startup failure,
    not a degraded feature. It took production down once already.
    """

    def _mod_names(self):
        import ast

        names = {}
        for path in sorted((ROOT / "Mikobot/plugins").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                # Class-scoped __mod_name__ is legal and is not loader-visible.
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__mod_name__":
                        if isinstance(node.value, ast.Constant):
                            names.setdefault(
                                node.value.value.lower(), []
                            ).append(path.name)
        return names

    def test_no_duplicate_mod_names(self):
        names = self._mod_names()
        duplicates = {
            name: owners for name, owners in names.items() if len(owners) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "duplicate __mod_name__ would abort startup in Mikobot/__main__.py",
        )


class AntiRaidTests(unittest.TestCase):
    """AntiRaid bans joiners for a window that has to expire on its own."""

    def test_raid_state_expires_without_a_background_task(self):
        # is_raid compares against the clock rather than trusting a stored
        # flag, so a raid still ends if the process restarted after it was set.
        source = (ROOT / "Database" / "sql" / "raid_sql.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "is_raid"
        )
        self.assertTrue(
            any(
                isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.Gt)
                for n in ast.walk(func)
            ),
            "is_raid must compare raid_until against the current time",
        )

    def test_defaults_match_the_documented_windows(self):
        # Read the constants instead of re-executing the module: loading
        # raid_sql a second time would declare raid_chats twice against the
        # shared MetaData and break every other SQL test in the process.
        # The values are written as arithmetic, which literal_eval rejects.
        source = (ROOT / "Database" / "sql" / "raid_sql.py").read_text(encoding="utf-8")
        wanted = ("DEF_RAID_TIME", "DEF_ACTION_TIME", "DEF_AUTO_ANTIRAID")
        constants = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign):
                name = getattr(node.targets[0], "id", "")
                if name in wanted:
                    constants[name] = eval(
                        ast.unparse(node.value), {"__builtins__": {}}, {}
                    )
        self.assertEqual(constants["DEF_RAID_TIME"], 6 * 60 * 60)
        self.assertEqual(constants["DEF_ACTION_TIME"], 60 * 60)
        self.assertEqual(constants["DEF_AUTO_ANTIRAID"], 0)

    def test_every_documented_command_is_registered(self):
        source = (ROOT / "Mikobot" / "plugins" / "antiraid.py").read_text(
            encoding="utf-8"
        )
        for command in ("antiraid", "raidtime", "raidactiontime", "autoantiraid"):
            self.assertIn(f'disableable("{command}")', source, command)

    def test_on_off_words_match_the_documented_forms(self):
        tree = ast.parse((ROOT / "Mikobot" / "plugins" / "antiraid.py").read_text(encoding="utf-8"))
        words = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                name = getattr(node.targets[0], "id", "")
                if name in ("ON_WORDS", "OFF_WORDS"):
                    words[name] = set(ast.literal_eval(node.value))
        self.assertEqual(words["ON_WORDS"], {"on", "yes", "true", "enable", "1"})
        self.assertEqual(words["OFF_WORDS"], {"off", "no", "false", "disable", "0"})

    def test_join_handler_cannot_ban_an_admin_or_a_bot(self):
        source = (ROOT / "Mikobot" / "plugins" / "antiraid.py").read_text(encoding="utf-8")
        self.assertIn("new_user.is_bot", source)
        self.assertIn("ChatMemberStatus.ADMINISTRATOR", source)
        self.assertIn("ChatID.ANONYMOUS_ADMIN", source)
        self.assertIn("is_approved", source)

    def test_duration_formatting_round_trips_through_the_time_parser(self):
        import asyncio as _asyncio

        from Mikobot.plugins.antiraid import format_duration
        from Mikobot.plugins.helper_funcs.string_handling import extract_time

        class _Msg:
            async def reply_text(self, text, *a, **k):
                return None

        for seconds in (90 * 60, 12 * 3600, 3 * 86400, 2 * 604800):
            shown = format_duration(seconds)
            expiry = _asyncio.run(extract_time(_Msg(), shown))
            self.assertIsNotNone(expiry, shown)
            self.assertAlmostEqual(expiry - int(__import__("time").time()), seconds, delta=5)

    def test_extract_time_accepts_weeks(self):
        # The documented duration table includes weeks; the shared parser is
        # the only place a duration is turned into an absolute expiry.
        import time as _time

        from Mikobot.plugins.helper_funcs.string_handling import extract_time

        class _Msg:
            async def reply_text(self, text, *a, **k):
                return None

        expiry = asyncio.run(extract_time(_Msg(), "2w"))
        self.assertIsNotNone(expiry)
        self.assertAlmostEqual(expiry - int(_time.time()), 2 * 7 * 86400, delta=5)

    def test_log_messages_escape_the_chat_title(self):
        tree = ast.parse((ROOT / "Mikobot" / "plugins" / "antiraid.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                blob = ast.unparse(node)
                if "chat.title" in blob:
                    self.assertIn(
                        "html.escape(chat.title)", blob,
                        "log_channel output is HTML; an unescaped title is spoofable",
                    )


def _registered_commands(path: Path) -> set:
    """Every command name a module registers, in any of the three idioms.

    The repo uses Command("x"), Command(commands=["x", "y"]), and a tuple loop
    that builds a name per iteration, so all three have to be collected for
    this to mean anything.
    """
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") == "Command":
            for arg in list(node.args) + [
                kw.value for kw in node.keywords if kw.arg == "commands"
            ]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
                elif isinstance(arg, (ast.List, ast.Tuple)):
                    found.update(
                        element.value
                        for element in ast.walk(arg)
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                    )
        elif getattr(node.func, "id", "") == "disableable":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
                elif isinstance(arg, (ast.List, ast.Tuple)):
                    found.update(
                        element.value
                        for element in ast.walk(arg)
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                    )
        elif getattr(node.func, "id", "") == "chain":
            # ("name", handler) tuples, registered in a loop below.
            continue
    # tuple loop: for _name, _handler in (("cleanservice", f), ...)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            for element in ast.walk(node.iter):
                if (
                    isinstance(element, ast.Tuple)
                    and element.elts
                    and isinstance(element.elts[0], ast.Constant)
                    and isinstance(element.elts[0].value, str)
                ):
                    found.add(element.elts[0].value)
    return found


class BlacklistMatchingTests(unittest.TestCase):
    """Blocklist matching is the anti-spam surface, so the rules are pinned here.

    The matcher is loaded from source rather than imported: importing the plugin
    pulls in the whole bot, and a second definition of a SQLAlchemy table would
    break the other SQL tests in this process.
    """

    @classmethod
    def setUpClass(cls):
        import unicodedata

        path = ROOT / "Mikobot" / "plugins" / "blacklist.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        wanted = {
            "normalize_text", "parse_trigger", "matches_text",
            "_wildcard_pattern", "_base_pattern", "_match_pattern",
            "_file_match", "TYPED_PREFIXES",
        }
        keep = []
        for node in tree.body:
            name = getattr(node, "name", None)
            if name in wanted:
                keep.append(node)
            elif isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", ""
            ) in wanted:
                keep.append(node)
        namespace = {"re": re, "unicodedata": unicodedata, "Message": object}
        exec(  # noqa: S102 - exercising the real source, not a copy
            compile(ast.Module(body=keep, type_ignores=[]), "<blacklist>", "exec"),
            namespace,
        )
        # staticmethod keeps these plain functions; a bare assignment would
        # bind them as methods and pass self as the first argument.
        cls.matches = staticmethod(namespace["matches_text"])
        cls.parse_trigger = staticmethod(namespace["parse_trigger"])
        cls.file_match = staticmethod(namespace["_file_match"])

    def test_plain_triggers_match_whole_words_only(self):
        # "hi" must not fire inside "this", or every mention trips a filter.
        self.assertTrue(self.matches("hi", "hi there"))
        self.assertTrue(self.matches("hi", "say hi!"))
        self.assertFalse(self.matches("hi", "this"))
        self.assertFalse(self.matches("hi", "his"))

    def test_typed_prefixes_are_recognised(self):
        for kind in (
            "prefix", "exact", "lookalike", "name", "username", "file",
            "forward", "inline", "stickerpack", "emojipack",
        ):
            self.assertEqual(
                self.parse_trigger(f"{kind}:payload"), (kind, "payload")
            )
        self.assertEqual(self.parse_trigger("earn"), (None, "earn"))

    def test_modifiers(self):
        self.assertTrue(self.matches("bit?", "bits"))
        self.assertFalse(self.matches("bit?", "bit"))
        self.assertTrue(self.matches("earn*", "earnings are up"))
        self.assertTrue(self.matches("earn*", "learn to earn"))

    def test_trigger_text_cannot_inject_a_regex(self):
        # Everything but ? and * is escaped, so a trigger is always literal.
        self.assertFalse(self.matches("a.b", "axb"))
        self.assertTrue(self.matches("a.b", "a.b"))
        self.assertFalse(self.matches("(a|b)", "a"))

    def test_prefix_and_exact_scoping(self):
        self.assertTrue(self.matches("prefix:earn", "earn money now"))
        self.assertFalse(self.matches("prefix:earn", "please earn money"))
        self.assertTrue(self.matches("exact:hi", "hi"))
        self.assertFalse(self.matches("exact:hi", "hi there"))

    def test_messages_are_normalised_before_matching(self):
        # Accents, case, curly quotes and padded whitespace must not hide a hit.
        self.assertTrue(self.matches("hi", "hî"))
        self.assertTrue(self.matches("hi there", "HI THERE"))
        self.assertTrue(self.matches("hi there", "hi   there"))
        self.assertTrue(self.matches("hi", "hî"))

    def test_lookalike_catches_homoglyphs_and_digits(self):
        self.assertTrue(self.matches("lookalike:bot", "b0t"))
        self.assertTrue(self.matches("lookalike:bot", "\u0432\u043e\u0442"))
        self.assertFalse(self.matches("lookalike:bot", "bots"))

    def test_file_extension_wildcards(self):
        self.assertTrue(self.file_match("*.pdf", "report.pdf"))
        self.assertFalse(self.file_match("*.pdf", "report.docx"))
        self.assertTrue(self.file_match("docs.pdf", "docs.pdf"))


class BlocklistModeTests(unittest.TestCase):
    """Delete and punishment are separate settings, plus owner-gated silence."""

    def test_documented_blocklist_commands_are_registered(self):
        registered = _registered_commands(
            ROOT / "Mikobot" / "plugins" / "blacklist.py"
        )
        # blacklistmode keeps this repo's existing name for the action setting;
        # the new commands follow the documented spellings.
        for command in ("blacklistmode", "blocklistdelete", "silentactions"):
            self.assertIn(command, registered)

    def test_silent_actions_require_the_owner(self):
        tree = ast.parse(
            (ROOT / "Mikobot" / "plugins" / "blacklist.py").read_text(
                encoding="utf-8"
            )
        )
        func = next(
            n for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "silent_actions"
        )
        decorators = " ".join(ast.unparse(d) for d in func.decorator_list)
        self.assertIn("only_owner=True", decorators)

    def test_silent_actions_demand_a_log_channel(self):
        # Otherwise a silent ban leaves no record at all.
        source = (ROOT / "Mikobot" / "plugins" / "blacklist.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("get_chat_log_channel", source)


class DeleteThenActTests(unittest.TestCase):
    """/dban, /dmute and /dkick remove the offending message as well.

    The /d form is reply-only: there is no message to delete otherwise, so
    acting anyway would punish the wrong thing.
    """

    def test_delete_variants_are_registered(self):
        for module, expected in (
            ("ban", {"dban", "dkick"}),
            ("mute", {"dmute", "dtmute"}),
        ):
            found = _registered_commands(ROOT / "Mikobot" / "plugins" / f"{module}.py")
            self.assertTrue(expected.issubset(found), f"{module}: {expected - found}")

    def test_delete_variants_require_a_reply(self):
        for module in ("ban", "mute"):
            source = (ROOT / "Mikobot" / "plugins" / f"{module}.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("not message.reply_to_message", source, module)

    def test_kick_awaits_the_unban_call(self):
        # PTB's unban_member returned a truthy value; aiogram returns a
        # coroutine. Un-awaited, every kick reported success even when
        # Telegram had refused it and the failure branch was unreachable.
        source = (ROOT / "Mikobot" / "plugins" / "ban.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("res = chat.unban_member(user_id)", source)
        self.assertIn("await bot.unban_chat_member(chat.id, user_id)", source)


class CleanServiceTests(unittest.TestCase):
    """Service cleaning can target specific types instead of all of them."""

    def test_documented_types_are_offered(self):
        source = (ROOT / "Mikobot" / "plugins" / "welcome.py").read_text(
            encoding="utf-8"
        )
        for name in ("join", "leave", "pin", "photo", "title", "videochat", "other"):
            self.assertIn(f'"{name}"', source, name)

    def test_commands_are_registered(self):
        found = _registered_commands(ROOT / "Mikobot" / "plugins" / "welcome.py")
        for command in ("cleanservice", "nocleanservice", "cleanservicetypes"):
            self.assertIn(command, found, command)

    def test_type_list_is_consulted_before_deleting(self):
        source = (ROOT / "Mikobot" / "plugins" / "welcome.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("get_service_types", source)
        # An empty list must keep the original delete-everything behaviour.
        self.assertIn("if not wanted:", source)


if __name__ == "__main__":
    unittest.main()