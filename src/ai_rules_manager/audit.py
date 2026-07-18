from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from .safe_fs import atomic_write_text

SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github-token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "assigned-secret": re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"),
}
INJECTION_PATTERNS = {
    "ignore-instructions": re.compile(r"(?i)ignore\s+(?:all\s+|any\s+)?(?:previous|prior)\s+instructions"),
    "system-message": re.compile(r"(?i)\b(?:system|developer)\s+message\s*:"),
    "role-override": re.compile(r"(?i)\byou\s+are\s+now\s+(?:the|a)\b"),
    "tool-directive": re.compile(r"(?i)\b(?:run|execute|invoke)\s+(?:this\s+)?(?:command|tool|shell)\b"),
}
TEXT_SUFFIXES = {".md", ".toml", ".json", ".py", ".sh", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "target", "coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "data", "datasets",
    "logs", "backups", "archives", "models", "checkpoints",
}
MAX_TEXT_FILE_BYTES = 1_000_000
MAX_AUDIT_FILES = 50_000
ALLOWED_HOOK_EVENTS = {"SessionStart", "PreCompact", "UserPromptSubmit", "Stop"}
ALLOWED_HOOK_SCRIPTS = {"session_start.py", "pre_compact.py", "user_prompt_submit.py", "stop.py"}
HOOK_PREFIX = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/'


@dataclass(slots=True)
class Finding:
    severity: str
    code: str
    path: str
    message: str


def _walk_once(root: Path):
    count = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs = []
        for name in dirs:
            path = current_path / name
            try:
                info = path.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                yield "symlink", path
                continue
            if name not in SKIP_DIRS:
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in files:
            path = current_path / name
            count += 1
            if count > MAX_AUDIT_FILES:
                yield "limit", path
                return
            try:
                info = path.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                yield "symlink", path
            elif stat.S_ISREG(info.st_mode):
                yield "file", path


def _audit_hooks(root: Path, findings: list[Finding]) -> None:
    hooks = root / ".codex" / "hooks.json"
    if not hooks.is_file() or hooks.is_symlink():
        return
    try:
        hooks_data = json.loads(hooks.read_text(encoding="utf-8"))
        configured = hooks_data.get("hooks", {})
        if not isinstance(configured, dict):
            raise ValueError("hooks must be an object")
        for event, groups in configured.items():
            if event not in ALLOWED_HOOK_EVENTS:
                findings.append(Finding("high", "HOOK_EVENT", ".codex/hooks.json", f"unexpected hook event: {event}"))
            if not isinstance(groups, list):
                raise ValueError(f"hook event {event} must be a list")
            for group in groups:
                for handler in group.get("hooks", []):
                    command = handler.get("command")
                    timeout = handler.get("timeout")
                    if not isinstance(command, str) or not command.startswith(HOOK_PREFIX) or not command.endswith('"'):
                        findings.append(Finding("high", "HOOK_COMMAND", ".codex/hooks.json", f"unexpected hook command: {command}"))
                        continue
                    script = command[len(HOOK_PREFIX):-1]
                    if script not in ALLOWED_HOOK_SCRIPTS or "/" in script or "\\" in script:
                        findings.append(Finding("high", "HOOK_SCRIPT", ".codex/hooks.json", f"unexpected hook script: {script}"))
                    if not isinstance(timeout, int) or timeout != 1:
                        findings.append(Finding("high", "HOOK_TIMEOUT", ".codex/hooks.json", f"hook timeout must be exactly 1 second: {timeout}"))
    except (OSError, ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        findings.append(Finding("high", "HOOKS_INVALID", ".codex/hooks.json", str(exc)))


def audit_project(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    root = root.resolve()
    for kind, path in _walk_once(root):
        relative = str(path.relative_to(root))
        if kind == "limit":
            findings.append(Finding("medium", "AUDIT_LIMIT", relative, f"audit stopped after {MAX_AUDIT_FILES} files"))
            break
        if kind == "symlink":
            try:
                target = path.resolve(strict=False)
                target.relative_to(root)
            except ValueError:
                findings.append(Finding("high", "PATH_ESCAPE", relative, "symlink escapes repository root"))
            if relative in {"AGENTS.md", ".codex/hooks.json", ".ai-rules/manifest.json", ".planning/.active_plan"} or relative.startswith(".codex/hooks/"):
                findings.append(Finding("critical", "CONTROL_SYMLINK", relative, "trusted control path must not be a symlink"))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_TEXT_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(Finding("critical", "SECRET", relative, f"possible {name}"))
        if path.name == "task_plan.md" or "rules" in path.parts:
            for name, pattern in INJECTION_PATTERNS.items():
                if pattern.search(text):
                    findings.append(Finding("high", "PROMPT_INJECTION", relative, f"trusted control file contains {name} pattern"))

    _audit_hooks(root, findings)

    manifest_path = root / ".ai-rules" / "manifest.json"
    if manifest_path.is_file() and not manifest_path.is_symlink():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest.get("files", {})
            if not isinstance(files, dict):
                raise ValueError("manifest.files must be an object")
            for relative, expected in files.items():
                candidate = root / relative
                if candidate.is_symlink():
                    findings.append(Finding("critical", "MANIFEST_SYMLINK", relative, "generated file is a symlink"))
                    continue
                resolved = candidate.resolve(strict=False)
                try:
                    resolved.relative_to(root)
                except ValueError:
                    findings.append(Finding("high", "MANIFEST_PATH", relative, "manifest path escapes root"))
                    continue
                if not candidate.is_file():
                    findings.append(Finding("high", "MANIFEST_MISSING", relative, "generated file is missing"))
                    continue
                actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if actual != expected:
                    findings.append(Finding("high", "MANIFEST_TAMPER", relative, "generated file hash does not match manifest"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(Finding("high", "MANIFEST_INVALID", ".ai-rules/manifest.json", str(exc)))
    return findings


def write_report(root: Path, findings: list[Finding]) -> Path:
    root = root.resolve()
    relative = Path(".ai-rules/audit-report.json")
    atomic_write_text(root, relative, json.dumps({"findings": [asdict(item) for item in findings]}, indent=2, sort_keys=True) + "\n")
    return root / relative
