import os
import tempfile
import unittest
from pathlib import Path

from ai_rules_manager.cli import main


class CompileTests(unittest.TestCase):
    def test_init_generates_current_codex_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = main([
                "init", "--root", str(root), "--name", "demo",
                "--platform", "debian", "--domain", "infrastructure"
            ])
            self.assertEqual(code, 0)
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertTrue((root / ".agents/skills/ai-rules-manager/SKILL.md").is_file())
            self.assertTrue((root / ".codex/hooks.json").is_file())
            self.assertTrue((root / ".ai-rules/manifest.json").is_file())
            self.assertIn("Debian Platform", (root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_attestation_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(main(["init", "--root", str(root), "--name", "demo"]), 0)
            old = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(main(["attest"]), 0)
                self.assertEqual(main(["attest", "--show"]), 0)
                active = (root / ".planning/.active_plan").read_text().strip()
                plan = root / ".planning" / active / "task_plan.md"
                plan.write_text(plan.read_text() + "\nchanged\n")
                self.assertEqual(main(["attest", "--show"]), 1)
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
