from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
from datetime import date
from pathlib import Path

from .safe_fs import UnsafePathError, atomic_write_text, safe_directory, safe_regular_file

ATTESTATION_PREFIX = "hmac-sha256:"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized[:48] or "task"


def _key_path() -> Path:
    configured = os.environ.get("AI_RULES_ATTESTATION_KEY_FILE")
    return Path(configured).expanduser().absolute() if configured else Path.home() / ".config" / "ai-rules-manager" / "attestation.key"


def _load_or_create_key(*, create: bool) -> bytes:
    path = _key_path()
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink():
        raise UnsafePathError(f"attestation key directory is a symlink: {parent}")
    os.chmod(parent, 0o700)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise FileNotFoundError(f"attestation key not found: {path}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            key = secrets.token_bytes(32)
            os.write(fd, key)
            os.fsync(fd)
        finally:
            os.close(fd)
        return key
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"attestation key is not a regular file: {path}")
    if info.st_mode & 0o077:
        raise PermissionError(f"attestation key permissions must be 0600: {path}")
    data = path.read_bytes()
    if len(data) != 32:
        raise ValueError(f"attestation key must contain exactly 32 bytes: {path}")
    return data


def create_plan(root: Path, title: str) -> Path:
    root = root.resolve()
    plan_id = f"{date.today().isoformat()}-{_slug(title)}"
    safe_directory(root, ".planning")
    plan_dir = safe_directory(root, Path(".planning") / plan_id)
    if any(plan_dir.iterdir()):
        raise FileExistsError(plan_dir)
    atomic_write_text(
        root,
        Path(".planning") / plan_id / "task_plan.md",
        f"# Task Plan: {title}\n\n## Goal\n\nDescribe the verified outcome.\n\n"
        "## Phases\n\n### Phase 1: Scope\n**Status:** in_progress\n\n"
        "### Phase 2: Implement\n**Status:** pending\n\n"
        "### Phase 3: Validate\n**Status:** pending\n\n"
        "## Decisions\n\n- None yet.\n\n## Errors\n\n- None yet.\n",
    )
    atomic_write_text(
        root,
        Path(".planning") / plan_id / "findings.md",
        "# Findings\n\nStore external research, logs and untrusted source summaries here.\n",
    )
    atomic_write_text(
        root,
        Path(".planning") / plan_id / "progress.md",
        "# Progress\n\nRecord commands, changed files and test evidence here.\n",
    )
    atomic_write_text(root, ".planning/.active_plan", plan_id + "\n")
    return plan_dir


def _plan_files(root: Path) -> tuple[Path, Path, Path] | None:
    root = root.resolve()
    active = safe_regular_file(root, ".planning/.active_plan", required=False)
    if active is not None:
        plan_id = active.read_text(encoding="utf-8", errors="strict").strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", plan_id):
            return None
        plan_rel = Path(".planning") / plan_id / "task_plan.md"
        att_rel = Path(".planning") / plan_id / ".attestation"
        plan = safe_regular_file(root, plan_rel, required=False)
        if plan is not None:
            att = safe_regular_file(root, att_rel, required=False)
            return plan.parent, plan, att if att is not None else plan.parent / ".attestation"
    legacy = safe_regular_file(root, "task_plan.md", required=False)
    if legacy is not None:
        att = safe_regular_file(root, ".attestation", required=False)
        return root, legacy, att if att is not None else root / ".attestation"
    return None


def resolve_plan_dir(root: Path) -> Path | None:
    files = _plan_files(root)
    return files[0] if files else None


def _digest(plan: Path, key: bytes) -> str:
    return hmac.new(key, plan.read_bytes(), hashlib.sha256).hexdigest()


def attest(root: Path, clear: bool = False) -> str:
    files = _plan_files(root)
    if files is None:
        raise FileNotFoundError("no active task_plan.md")
    _, plan, attestation = files
    relative = attestation.relative_to(root.resolve())
    if clear:
        existing = safe_regular_file(root, relative, required=False)
        if existing is not None:
            existing.unlink()
        return "cleared"
    key = _load_or_create_key(create=True)
    digest = _digest(plan, key)
    atomic_write_text(root, relative, ATTESTATION_PREFIX + digest + "\n", mode=0o600)
    return digest


def verify_attestation(root: Path) -> tuple[bool, str]:
    files = _plan_files(root)
    if files is None:
        return False, "no active plan"
    _, plan, attestation = files
    if not attestation.is_file() or attestation.is_symlink():
        return False, "plan is not attested"
    raw = attestation.read_text(encoding="ascii", errors="strict").strip()
    if not raw.startswith(ATTESTATION_PREFIX):
        return False, "legacy or unsupported attestation; run rulesctl attest"
    try:
        key = _load_or_create_key(create=False)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    actual = _digest(plan, key)
    expected = raw.removeprefix(ATTESTATION_PREFIX)
    return hmac.compare_digest(expected, actual), actual


def phase_status(root: Path) -> tuple[int, int, str | None]:
    files = _plan_files(root)
    if files is None:
        return 0, 0, None
    text = files[1].read_text(encoding="utf-8", errors="replace")
    statuses = re.findall(r"\*\*Status:\*\*\s*([a-z_]+)", text, flags=re.IGNORECASE)
    complete = sum(item.lower() == "complete" for item in statuses)
    current_match = re.search(
        r"^###\s+(.+?)\s*$.*?\*\*Status:\*\*\s*in_progress",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return complete, len(statuses), current_match.group(1).strip() if current_match else None
