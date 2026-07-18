import tempfile
import unittest
from pathlib import Path

from ai_rules_manager.safe_fs import UnsafePathError, atomic_write_text


class SafeFilesystemTests(unittest.TestCase):
    def test_atomic_write_refuses_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            victim = Path(outside) / "victim"
            victim.write_text("safe", encoding="utf-8")
            (root / "AGENTS.md").symlink_to(victim)

            with self.assertRaises(UnsafePathError):
                atomic_write_text(root, "AGENTS.md", "owned")

            self.assertEqual(victim.read_text(encoding="utf-8"), "safe")

    def test_atomic_write_refuses_symlink_parent(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / ".codex").symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaises(UnsafePathError):
                atomic_write_text(root, ".codex/hooks.json", "{}")


if __name__ == "__main__":
    unittest.main()
