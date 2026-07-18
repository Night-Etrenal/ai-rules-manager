from __future__ import annotations

from .models import ProjectConfig, Resolution, Rule


def validate(config: ProjectConfig, rules: list[Rule], resolution: Resolution) -> list[str]:
    errors = config.errors()
    for rule in rules:
        errors.extend(rule.errors())
    for rule_id, duplicates in sorted(resolution.duplicates.items()):
        sources = ", ".join(item.source for item in duplicates)
        errors.append(f"duplicate rule id {rule_id!r}: {sources}")
    return errors
