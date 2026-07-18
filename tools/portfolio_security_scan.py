#!/usr/bin/env python3
"""Bounded, offline security audit for portfolio repositories.

The scanner reads only Git-tracked files. It never recursively inventories the
host filesystem and never prints matched secret material.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_TEXT_BYTES = 1 * 1024 * 1024
WARN_LARGE_BYTES = 10 * 1024 * 1024

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("TELEGRAM_BOT_TOKEN", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35,}\b")),
)

DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DESTRUCTIVE_ROOT_DELETE", re.compile(r"(?<![\w-])rm\s+-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*\s+/(?:\s|$)")),
    ("DESTRUCTIVE_GIT_CLEAN", re.compile(r"\bgit\s+clean\s+-[A-Za-z]*f[A-Za-z]*d[A-Za-z]*x\b")),
    ("DESTRUCTIVE_GIT_RESET", re.compile(r"\bgit\s+reset\s+--hard\b")),
    ("DOWNLOAD_EXECUTE", re.compile(r"\b(?:curl|wget)\b[^\n|;]{0,500}\|\s*(?:sudo\s+)?(?:ba)?sh\b")),
    ("FILESYSTEM_FORMAT", re.compile(r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b")),
    ("RAW_DEVICE_WRITE", re.compile(r"\bdd\b[^\n]{0,300}\bof=/dev/")),
)

RUNTIME_DB_NAMES = {
    "logs_2.sqlite",
    "logs_2.sqlite-wal",
    "logs_2.sqlite-shm",
    "state_5.sqlite",
    "state_5.sqlite-wal",
    "state_5.sqlite-shm",
}

SENSITIVE_TRACKED_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}

TEXT_SUFFIXES = {
    ".c", ".cc", ".cfg", ".conf", ".cpp", ".css", ".env", ".go", ".h", ".hpp",
    ".html", ".ini", ".java", ".js", ".json", ".jsx", ".md", ".mjs", ".py",
    ".rb", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml", ".zsh",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    detail: str


def run_git(root: Path, *args: str, check: bool = True) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return proc.stdout


def tracked_entries(root: Path) -> dict[str, str]:
    raw = run_git(root, "ls-files", "-z", "-s")
    entries: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, path_b = record.split(b"\t", 1)
        mode = meta.split(b" ", 1)[0].decode("ascii")
        path = path_b.decode("utf-8", errors="surrogateescape")
        entries[path] = mode
    return entries


def overlay_paths(root: Path, upstream_ref: str) -> set[str]:
    raw = run_git(root, "diff", "--name-only", "-z", f"{upstream_ref}...HEAD")
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in raw.split(b"\0")
        if item
    }


def is_probably_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {
        "AGENTS.md", "Dockerfile", "Makefile", "Procfile", "SECURITY.md",
    }


def is_example(path: PurePosixPath) -> bool:
    name = path.name.lower()
    return (
        name.endswith(".example")
        or name.endswith(".example.yml")
        or name.endswith(".example.yaml")
        or name.endswith(".sample")
        or "example" in path.parts
        or "examples" in path.parts
        or "fixtures" in path.parts
        or "testdata" in path.parts
    )


def check_action_pins(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
        return findings
    for line_no, line in enumerate(text.splitlines(), 1):
        match = re.search(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", line)
        if not match:
            continue
        action, ref = match.groups()
        if action.startswith("./") or action.startswith("docker://"):
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{40}", ref):
            findings.append(Finding(
                "error", "UNPINNED_ACTION", path,
                f"line {line_no}: third-party action must use a full 40-character commit SHA",
            ))
    return findings


def check_hook_budget(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if path != ".codex/hooks.json":
        return findings
    lowered = text.lower()
    if "sqlite3" in lowered or "logs_2.sqlite" in lowered or "state_5.sqlite" in lowered:
        findings.append(Finding(
            "error", "CODEX_DB_HOOK", path,
            "project hooks must never access Codex internal SQLite databases",
        ))
    if re.search(r"\b(find|tree|du)\s+(?:/|~|\$home)", lowered):
        findings.append(Finding(
            "error", "BROAD_HOOK_SCAN", path,
            "project hooks must not recursively scan the host filesystem",
        ))
    for value in re.findall(r'"timeout"\s*:\s*(\d+)', text):
        if int(value) > 5:
            findings.append(Finding(
                "warning", "HOOK_TIMEOUT", path,
                f"hook timeout {value}s exceeds the 5s repository safety budget",
            ))
    return findings


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_TEXT_BYTES or b"\0" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(root: Path, mode: str, upstream_ref: str | None) -> list[Finding]:
    root = root.resolve()
    entries = tracked_entries(root)
    selected = set(entries)
    if mode == "overlay":
        if not upstream_ref:
            raise ValueError("--upstream-ref is required in overlay mode")
        selected &= overlay_paths(root, upstream_ref)

    findings: list[Finding] = []
    for rel in sorted(selected):
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts:
            findings.append(Finding("error", "INVALID_PATH", rel, "tracked path escapes repository syntax"))
            continue

        mode_bits = entries[rel]
        path = root / Path(*pure.parts)
        if mode_bits == "120000":
            try:
                target = os.readlink(path)
            except OSError:
                findings.append(Finding("error", "BROKEN_SYMLINK", rel, "tracked symlink cannot be read"))
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                findings.append(Finding("error", "SYMLINK_ESCAPE", rel, "tracked symlink resolves outside repository"))
            continue

        try:
            size = path.stat().st_size
        except OSError:
            findings.append(Finding("error", "MISSING_TRACKED_FILE", rel, "tracked file is missing from checkout"))
            continue

        if pure.name in RUNTIME_DB_NAMES:
            findings.append(Finding(
                "error", "CODEX_RUNTIME_DB", rel,
                "Codex runtime databases and WAL/SHM files must never be committed",
            ))

        lower_name = pure.name.lower()
        if (
            lower_name in SENSITIVE_TRACKED_NAMES
            or lower_name.endswith((".pem", ".p12", ".pfx", ".kdbx"))
            or (lower_name.endswith(".key") and not is_example(pure))
        ) and not is_example(pure):
            findings.append(Finding(
                "error", "SENSITIVE_FILE", rel,
                "sensitive credential-like file is tracked; use a reviewed example file instead",
            ))

        if size > WARN_LARGE_BYTES:
            findings.append(Finding(
                "warning", "LARGE_TRACKED_FILE", rel,
                f"tracked file is {size} bytes; verify it belongs in Git/LFS",
            ))

        if not is_probably_text(path):
            continue
        text = read_text(path)
        if text is None:
            continue

        for code, pattern in SECRET_PATTERNS:
            if pattern.search(text) and not is_example(pure):
                findings.append(Finding(
                    "error", code, rel,
                    "high-confidence credential material detected; matched value is intentionally redacted",
                ))

        for code, pattern in DANGEROUS_PATTERNS:
            if pattern.search(text):
                findings.append(Finding(
                    "warning", code, rel,
                    "dangerous command pattern requires explicit scope, target inventory, confirmation and rollback",
                ))

        findings.extend(check_action_pins(rel, text))
        findings.extend(check_hook_budget(rel, text))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--mode", choices=("repository", "overlay"), default="repository")
    parser.add_argument("--upstream-ref")
    args = parser.parse_args(argv)

    try:
        findings = scan(args.root, args.mode, args.upstream_ref)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR SCANNER {exc}", file=sys.stderr)
        return 2

    for finding in findings:
        print(f"{finding.severity.upper()} {finding.code} {finding.path}: {finding.detail}")

    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    print(f"SUMMARY errors={errors} warnings={warnings} mode={args.mode}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
