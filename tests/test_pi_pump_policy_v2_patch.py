"""Guarded migration from the installed Pi pump policy; no hardware calls."""

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from deploy.apply_pi_pump_policy_v2 import (
    CONFIRM_NEW, CONFIRM_OLD, DB_PUMP_EVENTS, DB_RECENT,
    EARLY_NEW, EARLY_OLD, MARKER, RUNTIME_OLD, WEB_EVENT_ROUTE,
    WEB_IMPORT_V1, WEB_IMPORT_V2, WEB_NEW, WEB_OLD, WEB_PUMP_ROUTE,
    WEB_PUMP_ROUTE_V1, patch_database, patch_service, patch_web,
)


SERVICE = '''class Service:
    def sample(self):
        with self.lock:
''' + EARLY_OLD + '''
            if self.database_error:
                self.actuators.all_off("Database error")
                self.selected_mode = SEMI
            else:
                applied = self.actuators.apply(None, None, None, None, None)
''' + RUNTIME_OLD + '''                self.state["automation"] = applied
                if applied.get("dose_event"):
                    self.event("actuator", "Automatic dose completed", applied["dose_event"])
                    if self.database_error:
                        stopped = self.actuators.all_off("Automatic dose event could not be logged")
                        self.selected_mode = SEMI
                        self.state["database"] = {"status": "FAULT / ERROR"}
                        self.state["automation"]["active_mode"] = SEMI
                        self.state["automation"]["selected_mode"] = SEMI

    def tick(self):
        try:
            return self.sample()
        except Exception:
            with self.lock:
                self.actuators.all_off("Unexpected exception")
                self.selected_mode = SEMI

''' + CONFIRM_OLD + '\n'

WEB = '''import sqlite3
from urllib.parse import urlsplit

class Handler:
    def do_GET(self):
        from urllib.parse import parse_qs
        if True:
''' + WEB_EVENT_ROUTE + '''

    def do_POST(self):
        if True:
''' + WEB_OLD + '\n'

DATABASE = 'import sqlite3\n\nclass Database:\n' + DB_RECENT + '\n'


class PatchTests(unittest.TestCase):
    def test_installed_service_preserves_requested_full_mode_after_override(self):
        updated = patch_service(SERVICE)
        self.assertIn(MARKER, updated)
        self.assertIn(EARLY_NEW, updated)
        self.assertIn(CONFIRM_NEW, updated)
        self.assertNotIn('self.selected_mode = SEMI', updated)
        self.assertNotIn(RUNTIME_OLD, updated)
        self.assertEqual(patch_service(updated), updated)

    def test_history_route_and_database_query_are_idempotent(self):
        web = patch_web(WEB)
        database = patch_database(DATABASE)
        self.assertIn(WEB_NEW, web)
        self.assertIn(WEB_PUMP_ROUTE, web)
        self.assertIn(DB_PUMP_EVENTS, database)
        self.assertEqual(patch_web(web), web)
        self.assertEqual(patch_database(database), database)

    def test_installed_history_route_avoids_local_parser_import_shadow(self):
        installed = patch_web(WEB)
        installed = installed.replace(WEB_IMPORT_V2, WEB_IMPORT_V1)
        installed = installed.replace(WEB_PUMP_ROUTE, WEB_PUMP_ROUTE_V1)
        self.assertEqual(patch_web(installed), patch_web(WEB))
        self.assertIn(WEB_IMPORT_V2, patch_web(installed))

    def test_pump_history_query_keeps_older_doses_beyond_recent_event_limit(self):
        namespace = {"sqlite3": sqlite3}
        exec(patch_database(DATABASE), namespace)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.sqlite"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp TEXT, category TEXT, message TEXT, payload TEXT)")
                connection.execute("INSERT INTO events VALUES (1, '2026-10-29T14:00:00+08:00', 'actuator', 'Automatic dose completed', '{}')")
                for index in range(2, 43):
                    connection.execute("INSERT INTO events VALUES (?, '2026-10-29T14:00:30+08:00', 'status', 'Monitoring update', '{}')", (index,))
                connection.execute("INSERT INTO events VALUES (43, '2026-10-29T14:01:00+08:00', 'actuator', 'DOSED', '{}')")
                connection.commit()
            finally:
                connection.close()
            database = namespace["Database"]()

            @contextmanager
            def connect():
                connection = sqlite3.connect(path)
                try:
                    yield connection
                finally:
                    connection.close()

            database.connect = connect
            rows = database.pump_events("2026-10-29T05:59:59Z")
            self.assertEqual([row["id"] for row in rows], [43, 1])

    def test_unknown_installed_service_refuses_a_partial_patch(self):
        with self.assertRaisesRegex(ValueError, "live mode override"):
            patch_service(SERVICE.replace(EARLY_OLD, "# unknown mode implementation"))


if __name__ == "__main__":
    unittest.main()
