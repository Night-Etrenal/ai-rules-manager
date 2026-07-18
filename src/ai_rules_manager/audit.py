from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github-token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "assigned-secret": re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,}"),
}

INJECTION_PATTERNS = {
    "ignore-instructions": re.compile(r"(?i)ignore (?:all |any )?(?:previous|prior) instructions"),
    "system-message": re.compile(r"(?i)\b(?:system|developer) message\s*:"),
    "role-override": re.compile(r"(?i)you are now (?:the|a)"),
}

TEXT_SUFFIXES = {".md", ".toml", ".json", ".py", ".sh", ".txt", ".yaml", ".yml"}
SKIP_PARTS = {".git", ".venv", "dist", "build", "__pycache__"}


@dataclass(slots=True)
class Finding:
    severity: str
    code: str
    path: str
    message: str


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        yield path


def audit_project(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    resolved_root = root.resolve()

    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = path.resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            findings.append(Finding("high", "PATH_ESCAPE", str(path.relative_to(root)), "symlink escapes repository root"))

    for path in _iter_text_files(root):
        relative = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(Finding("critical", "SECRET", relative, f"possible {name}"))
        if path.name == "task_plan.md" or "rules" in path.parts:
            for name, pattern in INJECTION_PATTERNS.items():
                if pattern.search(text):
                    findings.append(Finding("high", "PROMPT_INJECTION", relative, f"trusted control file contains {name} pattern"))

    hooks = root / ".codex" / "hooks.json"
    if hooks.is_file():
        try:
            hooks_data = json.loads(hooks.read_text(encoding="utf-8"))
            commands: list[str] = []
            for groups in hooks_data.get("hooks", {}).values():
                for group in groups:
                    for handler in group.get("hooks", []):
                        command = handler.get("command")
                        if isinstance(command, str):
                            commands.append(command)
            for command in commands:
                if not command.startswith("/usr/bin/python3 ") or ".codex/hooks/" not in command:
                    findings.append(Finding("high", "HOOK_COMMAND", ".codex/hooks.json", f"unexpected hook command: {command}"))
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            findings.append(Finding("high", "HOOKS_INVALID", ".codex/hooks.json", str(exc)))

    manifest_path = root / ".ai-rules" / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for relative, expected in manifest.get("files", {}).items():
                candidate = (root / relative).resolve()
                try:
                    candidate.relative_to(resolved_root)
                except ValueError:
                    findings.append(Finding("high", "MANIFEST_PATH", relative, "manifest path escapes root"))
                    continue
                if not candidate.is_file():
                    findings.append(Finding("high", "MANIFEST_MISSING", relative, "generated file is missing"))
                    continue
                actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if actual != expected:
                    findings.append(Finding("high", "MANIFEST_TAMPER", relative, "generated file hash does not match manifest"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(Finding("high", "MANIFEST_INVALID", ".ai-rules/manifest.json", str(exc)))

    return findings


def write_report(root: Path, findings: list[Finding]) -> Path:
    report = root / ".ai-rules" / "audit-report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps({"findings": [asdict(item) for item in findings]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report
