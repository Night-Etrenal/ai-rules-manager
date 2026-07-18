import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_rules_manager.codex_io import (
    CodexActiveError,
    CodexProcess,
    TRIGGER_NAME,
    apply_log_guard,
    audit_codex_io,
    restore_log_writes,
)


def create_database(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    db = home / "logs_2.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, message TEXT)"
        )
        connection.execute("INSERT INTO logs(level, message) VALUES ('TRACE', 'before')")
        connection.commit()
    return db


class CodexIOTests(unittest.TestCase):
    def test_audit_is_read_only_and_reports_static_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            create_database(home)
            result = audit_codex_io(
                home,
                samples=2,
                interval=0,
                process_detector=lambda: [],
                sleeper=lambda _: None,
            )
            self.assertEqual(result.risk, "normal")
            self.assertEqual(result.max_id_growth, 0)
            self.assertEqual(result.wal_growth_bytes, 0)

    def test_guard_refuses_when_codex_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            create_database(home)
            with self.assertRaises(CodexActiveError):
                apply_log_guard(
                    home,
                    process_detector=lambda: [CodexProcess(123, "codex app-server")],
                )
            self.assertFalse((home / "backups").exists())

    def test_guard_blocks_insert_and_restore_reenables_logging(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = create_database(home)
            guarded = apply_log_guard(home, process_detector=lambda: [])
            self.assertTrue(guarded.backup_dir.is_dir())
            with sqlite3.connect(db) as connection:
                trigger = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
                    (TRIGGER_NAME,),
                ).fetchone()[0]
                connection.execute("INSERT INTO logs(level, message) VALUES ('TRACE', 'blocked')")
                count = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            self.assertEqual(trigger, 1)
            self.assertEqual(count, 1)

            restored = restore_log_writes(home, process_detector=lambda: [])
            self.assertTrue(restored.backup_dir.is_dir())
            with sqlite3.connect(db) as connection:
                connection.execute("INSERT INTO logs(level, message) VALUES ('TRACE', 'restored')")
                count = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
                trigger = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
                    (TRIGGER_NAME,),
                ).fetchone()[0]
            self.assertEqual(trigger, 0)
            self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
