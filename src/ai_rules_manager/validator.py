from __future__ import annotations

from .models import ProjectConfig, Resolution, Rule


def _priority_boundary_errors(rule: Rule) -> list[str]:
    errors: list[str] = []
    if rule.scope == "security" and rule.priority < 900:
        errors.append(f"{rule.source}: security rule {rule.id!r} must use priority 900-1000")
    elif rule.scope == "platform" and not 700 <= rule.priority <= 899:
        errors.append(f"{rule.source}: platform rule {rule.id!r} must use priority 700-899")
    elif rule.scope not in {"security", "platform"} and rule.priority >= 700:
        errors.append(
            f"{rule.source}: {rule.scope} rule {rule.id!r} may not enter reserved platform/security priority range 700-1000"
        )
    return errors


def validate(config: ProjectConfig, rules: list[Rule], resolution: Resolution) -> list[str]:
    errors = config.errors()
    for rule in rules:
        errors.extend(rule.errors())
        errors.extend(_priority_boundary_errors(rule))
    for rule_id, duplicates in sorted(resolution.duplicates.items()):
        sources = ", ".join(item.source for item in duplicates)
        errors.append(f"duplicate rule id {rule_id!r}: {sources}")
    return errors
