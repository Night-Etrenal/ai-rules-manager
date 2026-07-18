import os
import tempfile
import unittest
from pathlib import Path

from ai_rules_manager.planning import attest, create_plan, verify_attestation
from ai_rules_manager.safe_fs import UnsafePathError


class PlanningSecurityTests(unittest.TestCase):
    def test_plan_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                root = Path(tmp)
                plan = create_plan(root, "security")
                victim = Path(home) / "secret"
                victim.write_text("secret", encoding="utf-8")
                (plan / "task_plan.md").unlink()
                (plan / "task_plan.md").symlink_to(victim)

                with self.assertRaises(UnsafePathError):
                    attest(root)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_hmac_attestation_detects_plan_change(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                root = Path(tmp)
                plan = create_plan(root, "security")
                attest(root)
                self.assertTrue(verify_attestation(root)[0])
                task = plan / "task_plan.md"
                task.write_text(task.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
                self.assertFalse(verify_attestation(root)[0])
                key = Path(home) / ".config/ai-rules-manager/attestation.key"
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home


if __name__ == "__main__":
    unittest.main()
