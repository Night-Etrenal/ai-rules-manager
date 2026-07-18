from __future__ import annotations

from collections import defaultdict

from .models import Conflict, Resolution, Rule


def resolve_rules(rules: list[Rule]) -> Resolution:
    enabled = [rule for rule in rules if rule.enabled]
    by_id: dict[str, list[Rule]] = defaultdict(list)
    by_key: dict[str, list[Rule]] = defaultdict(list)
    for rule in enabled:
        by_id[rule.id].append(rule)
        by_key[rule.key].append(rule)

    duplicates = {key: items for key, items in by_id.items() if len(items) > 1}
    active: list[Rule] = []
    conflicts: list[Conflict] = []

    for key, candidates in by_key.items():
        ordered = sorted(candidates, key=lambda item: item.effective_rank, reverse=True)
        winner = ordered[0]
        active.append(winner)
        shadowed = tuple(item for item in ordered[1:] if item.value != winner.value)
        if shadowed:
            conflicts.append(Conflict(key=key, winner=winner, shadowed=shadowed))

    active.sort(key=lambda item: (-item.priority, item.category, item.id))
    conflicts.sort(key=lambda item: item.key)
    return Resolution(active=active, conflicts=conflicts, duplicates=duplicates)
