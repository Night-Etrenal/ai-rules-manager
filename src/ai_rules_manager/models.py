from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCOPE_ORDER = {
    "task": 100,
    "project": 200,
    "domain": 300,
    "global": 400,
    "platform": 500,
    "security": 600,
}

VALID_CONTEXT_MODES = {"minimal", "balanced", "strict"}


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    title: str
    scope: str
    priority: int
    key: str
    value: str
    instruction: str
    category: str = "general"
    enabled: bool = True
    tags: tuple[str, ...] = ()
    source: str = ""

    @property
    def effective_rank(self) -> tuple[int, int, str]:
        return (self.priority, SCOPE_ORDER.get(self.scope, 0), self.id)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any], source: Path | str) -> "Rule":
        tags = mapping.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise ValueError("rule.tags must be an array of strings")
        return cls(
            id=str(mapping.get("id", "")).strip(),
            title=str(mapping.get("title", "")).strip(),
            scope=str(mapping.get("scope", "")).strip(),
            priority=int(mapping.get("priority", 0)),
            key=str(mapping.get("key", "")).strip(),
            value=str(mapping.get("value", "")).strip(),
            instruction=str(mapping.get("instruction", "")).strip(),
            category=str(mapping.get("category", "general")).strip() or "general",
            enabled=bool(mapping.get("enabled", True)),
            tags=tuple(tags),
            source=str(source),
        )

    def errors(self) -> list[str]:
        errors: list[str] = []
        for name in ("id", "title", "scope", "key", "value", "instruction"):
            if not getattr(self, name):
                errors.append(f"{self.source}: rule.{name} is required")
        if self.scope not in SCOPE_ORDER:
            errors.append(f"{self.source}: unsupported scope {self.scope!r}")
        if not 1 <= self.priority <= 1000:
            errors.append(f"{self.source}: priority must be between 1 and 1000")
        return errors


@dataclass(slots=True)
class ProjectConfig:
    root: Path
    name: str
    platform: str
    domains: list[str]
    context_mode: str
    bundles: list[str]
    extra_rule_paths: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=lambda: ["all"])

    def errors(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("project.name is required")
        if self.platform != "debian":
            errors.append("MVP supports only platform='debian'")
        if self.context_mode not in VALID_CONTEXT_MODES:
            errors.append(f"context_mode must be one of {sorted(VALID_CONTEXT_MODES)}")
        if not self.bundles:
            errors.append("selection.bundles must not be empty")
        return errors


@dataclass(frozen=True, slots=True)
class Conflict:
    key: str
    winner: Rule
    shadowed: tuple[Rule, ...]


@dataclass(slots=True)
class Resolution:
    active: list[Rule]
    conflicts: list[Conflict]
    duplicates: dict[str, list[Rule]]
