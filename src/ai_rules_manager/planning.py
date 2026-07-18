from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized[:48] or "task"


def create_plan(root: Path, title: str) -> Path:
    plan_id = f"{date.today().isoformat()}-{_slug(title)}"
    plan_dir = root / ".planning" / plan_id
    plan_dir.mkdir(parents=True, exist_ok=False)
    (plan_dir / "task_plan.md").write_text(
        f"# Task Plan: {title}\n\n## Goal\n\nDescribe the verified outcome.\n\n"
        "## Phases\n\n### Phase 1: Scope\n**Status:** in_progress\n\n"
        "### Phase 2: Implement\n**Status:** pending\n\n"
        "### Phase 3: Validate\n**Status:** pending\n\n"
        "## Decisions\n\n- None yet.\n\n## Errors\n\n- None yet.\n",
        encoding="utf-8",
    )
    (plan_dir / "findings.md").write_text(
        "# Findings\n\nStore external research, logs and untrusted source summaries here.\n",
        encoding="utf-8",
    )
    (plan_dir / "progress.md").write_text(
        "# Progress\n\nRecord commands, changed files and test evidence here.\n",
        encoding="utf-8",
    )
    active = root / ".planning" / ".active_plan"
    active.write_text(plan_id + "\n", encoding="utf-8")
    return plan_dir


def resolve_plan_dir(root: Path) -> Path | None:
    planning = root / ".planning"
    active = planning / ".active_plan"
    if active.is_file():
        plan_id = active.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", plan_id):
            candidate = (planning / plan_id).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                return None
            if (candidate / "task_plan.md").is_file():
                return candidate
    legacy = root / "task_plan.md"
    return root if legacy.is_file() else None


def attest(root: Path, clear: bool = False) -> str:
    plan_dir = resolve_plan_dir(root)
    if plan_dir is None:
        raise FileNotFoundError("no active task_plan.md")
    plan = plan_dir / "task_plan.md"
    attestation = plan_dir / ".attestation"
    if clear:
        attestation.unlink(missing_ok=True)
        return "cleared"
    digest = hashlib.sha256(plan.read_bytes()).hexdigest()
    temp = attestation.with_suffix(".tmp")
    temp.write_text(digest + "\n", encoding="ascii")
    temp.replace(attestation)
    return digest


def verify_attestation(root: Path) -> tuple[bool, str]:
    plan_dir = resolve_plan_dir(root)
    if plan_dir is None:
        return False, "no active plan"
    attestation = plan_dir / ".attestation"
    if not attestation.is_file():
        return False, "plan is not attested"
    expected = attestation.read_text(encoding="ascii").strip()
    actual = hashlib.sha256((plan_dir / "task_plan.md").read_bytes()).hexdigest()
    return expected == actual, actual


def phase_status(root: Path) -> tuple[int, int, str | None]:
    plan_dir = resolve_plan_dir(root)
    if plan_dir is None:
        return 0, 0, None
    text = (plan_dir / "task_plan.md").read_text(encoding="utf-8", errors="replace")
    statuses = re.findall(r"\*\*Status:\*\*\s*([a-z_]+)", text, flags=re.IGNORECASE)
    complete = sum(item.lower() == "complete" for item in statuses)
    current_match = re.search(
        r"^###\s+(.+?)\s*$.*?\*\*Status:\*\*\s*in_progress",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return complete, len(statuses), current_match.group(1).strip() if current_match else None
