import unittest

from ai_rules_manager.models import Rule
from ai_rules_manager.resolver import resolve_rules


class ResolverTests(unittest.TestCase):
    def test_higher_priority_wins_and_conflict_is_reported(self):
        low = Rule("domain.os", "Domain OS", "domain", 500, "platform.os", "ubuntu", "Use Ubuntu")
        high = Rule("platform.os", "Platform OS", "platform", 900, "platform.os", "debian", "Use Debian")
        result = resolve_rules([low, high])
        self.assertEqual(result.active[0].id, "platform.os")
        self.assertEqual(result.conflicts[0].shadowed[0].id, "domain.os")

    def test_duplicate_ids_are_reported(self):
        one = Rule("same", "One", "global", 500, "a", "1", "one")
        two = Rule("same", "Two", "global", 400, "b", "2", "two")
        result = resolve_rules([one, two])
        self.assertIn("same", result.duplicates)


if __name__ == "__main__":
    unittest.main()
