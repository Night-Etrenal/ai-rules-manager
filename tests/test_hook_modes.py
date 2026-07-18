import json
import unittest
from pathlib import Path

from ai_rules_manager.compiler import render_hooks_json
from ai_rules_manager.models import ProjectConfig


class HookModeTests(unittest.TestCase):
    def config(self, mode: str) -> ProjectConfig:
        return ProjectConfig(
            root=Path("."),
            name="demo",
            platform="debian",
            domains=[],
            context_mode=mode,
            bundles=["core", "security", "platform/debian"],
        )

    def test_minimal_omits_high_frequency_hooks(self):
        hooks = json.loads(render_hooks_json(self.config("minimal")))["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreCompact"})

    def test_balanced_adds_user_prompt_only(self):
        hooks = json.loads(render_hooks_json(self.config("balanced")))["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreCompact", "UserPromptSubmit"})

    def test_strict_adds_stop_advisory(self):
        hooks = json.loads(render_hooks_json(self.config("strict")))["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreCompact", "UserPromptSubmit", "Stop"})
        for entries in hooks.values():
            for entry in entries:
                for hook in entry["hooks"]:
                    self.assertLessEqual(hook["timeout"], 1)


if __name__ == "__main__":
    unittest.main()
