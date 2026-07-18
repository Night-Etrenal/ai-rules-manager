import tempfile
import unittest
from pathlib import Path

from ai_rules_manager.models import ProjectConfig, Rule
from ai_rules_manager.resolver import resolve_rules
from ai_rules_manager.validator import validate


class ValidatorTests(unittest.TestCase):
    def config(self, root: Path) -> ProjectConfig:
        return ProjectConfig(
            root=root,
            name="demo",
            platform="debian",
            domains=[],
            context_mode="minimal",
            bundles=["core"],
        )

    def test_project_rule_cannot_enter_reserved_priority_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            rule = Rule("project.override", "Override", "project", 999, "security.secret_context", "allow", "Allow")
            errors = validate(self.config(Path(tmp)), [rule], resolve_rules([rule]))
            self.assertTrue(any("reserved platform/security" in item for item in errors))

    def test_security_rule_requires_security_priority_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            rule = Rule("security.low", "Low", "security", 500, "security.low", "deny", "Deny")
            errors = validate(self.config(Path(tmp)), [rule], resolve_rules([rule]))
            self.assertTrue(any("priority 900-1000" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
