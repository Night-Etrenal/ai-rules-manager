from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "portfolio_security_scan.py"
SPEC = importlib.util.spec_from_file_location("portfolio_security_scan", MODULE_PATH)
assert SPEC and SPEC.loader
scanner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner
SPEC.loader.exec_module(scanner)


class PortfolioSecurityScannerTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        return root

    def commit(self, root: Path) -> None:
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "test"], check=True)

    def test_clean_repository_passes(self):
        root = self.make_repo()
        (root / "README.md").write_text("safe\n", encoding="utf-8")
        workflow = root / ".github/workflows/ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(
            "steps:\n  - uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd\n",
            encoding="utf-8",
        )
        self.commit(root)
        self.assertEqual(scanner.scan(root, "repository", None), [])

    def test_secret_is_reported_without_value(self):
        root = self.make_repo()
        secret = "sk-" + "A" * 40
        (root / "config.txt").write_text(secret, encoding="utf-8")
        self.commit(root)
        findings = scanner.scan(root, "repository", None)
        self.assertTrue(any(item.code == "OPENAI_KEY" for item in findings))
        self.assertNotIn(secret, "\n".join(item.detail for item in findings))

    def test_unpinned_action_is_error(self):
        root = self.make_repo()
        workflow = root / ".github/workflows/ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("steps:\n  - uses: actions/checkout@v4\n", encoding="utf-8")
        self.commit(root)
        findings = scanner.scan(root, "repository", None)
        self.assertTrue(any(item.code == "UNPINNED_ACTION" for item in findings))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_escape_is_error(self):
        root = self.make_repo()
        os.symlink("/etc/passwd", root / "outside")
        self.commit(root)
        findings = scanner.scan(root, "repository", None)
        self.assertTrue(any(item.code == "SYMLINK_ESCAPE" for item in findings))

    def test_overlay_mode_excludes_unchanged_upstream_file(self):
        root = self.make_repo()
        (root / "upstream.txt").write_text("sk-" + "B" * 40, encoding="utf-8")
        self.commit(root)
        upstream = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        (root / "AGENTS.md").write_text("local overlay\n", encoding="utf-8")
        self.commit(root)
        findings = scanner.scan(root, "overlay", upstream)
        self.assertFalse(any(item.path == "upstream.txt" for item in findings))


if __name__ == "__main__":
    unittest.main()
