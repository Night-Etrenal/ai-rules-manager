from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import audit_project, write_report
from .codex_io import (
    DEFAULT_MAX_BACKUP_BYTES,
    DEFAULT_MAX_BACKUP_COUNT,
    DEFAULT_MAX_BACKUP_TOTAL_BYTES,
    apply_log_guard,
    audit_codex_io,
    find_codex_processes,
    resolve_codex_home,
    restore_log_writes,
    take_snapshot,
)
from .compiler import compile_project
from .config import CONFIG_NAME, available_bundles, find_project_root, load_config, load_rules
from .planning import attest, create_plan, phase_status, resolve_plan_dir, verify_attestation
from .resolver import resolve_rules
from .safe_fs import UnsafePathError, atomic_write_text
from .validator import validate


def _write_config(root: Path, name: str, platform: str, domains: list[str], mode: str) -> None:
    bundles = ["core", "security", f"platform/{platform}"] + [f"domains/{item}" for item in domains]
    domain_text = ", ".join(f'"{item}"' for item in domains)
    bundle_text = ",\n  ".join(f'"{item}"' for item in bundles)
    content = f'''version = 1

[project]
name = "{name}"
platform = "{platform}"
domains = [{domain_text}]
context_mode = "{mode}"

[selection]
bundles = [
  {bundle_text}
]
extra_rule_paths = []

[output]
targets = ["all"]
'''
    atomic_write_text(root, CONFIG_NAME, content)


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    config_path = root / CONFIG_NAME
    if config_path.exists() and not args.force:
        print(f"error: {config_path} already exists; use --force", file=sys.stderr)
        return 2
    if config_path.is_symlink():
        print(f"error: refusing symlink config path: {config_path}", file=sys.stderr)
        return 2
    _write_config(root, args.name, args.platform, args.domain, args.context_mode)
    config = load_config(root)
    rules = load_rules(config)
    resolution = resolve_rules(rules)
    errors = validate(config, rules, resolution)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    compile_project(config, resolution)
    if not (root / ".planning").exists():
        plan = create_plan(root, "Initial task")
        print(f"created plan: {plan.relative_to(root)}")
    print(f"initialized: {root}")
    return 0


def _loaded():
    config = load_config()
    rules = load_rules(config)
    resolution = resolve_rules(rules)
    return config, rules, resolution


def command_validate(_: argparse.Namespace) -> int:
    config, rules, resolution = _loaded()
    errors = validate(config, rules, resolution)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    for conflict in resolution.conflicts:
        print(f"warning: {conflict.key}: {conflict.winner.id} shadows {', '.join(item.id for item in conflict.shadowed)}")
    print(f"valid: {len(resolution.active)} active rules")
    return 0


def command_compile(args: argparse.Namespace) -> int:
    config, rules, resolution = _loaded()
    errors = validate(config, rules, resolution)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    for path in compile_project(config, resolution, args.target):
        print(path.relative_to(config.root))
    return 0


def command_list(_: argparse.Namespace) -> int:
    try:
        config, _, resolution = _loaded()
        for rule in resolution.active:
            print(f"{rule.priority:04d} {rule.scope:8s} {rule.id} = {rule.value}")
    except FileNotFoundError:
        for bundle in available_bundles():
            print(bundle)
    return 0


def command_audit(_: argparse.Namespace) -> int:
    root = find_project_root()
    findings = audit_project(root)
    report = write_report(root, findings)
    for item in findings:
        print(f"{item.severity.upper():8s} {item.code:18s} {item.path}: {item.message}")
    print(f"report: {report.relative_to(root)}")
    return 1 if any(item.severity in {"critical", "high"} for item in findings) else 0


def command_plan_init(args: argparse.Namespace) -> int:
    root = find_project_root()
    try:
        plan = create_plan(root, args.title)
    except FileExistsError as exc:
        print(f"error: plan already exists: {exc.filename or exc}", file=sys.stderr)
        return 2
    print(plan.relative_to(root))
    return 0


def command_plan_status(_: argparse.Namespace) -> int:
    root = find_project_root()
    directory = resolve_plan_dir(root)
    if directory is None:
        print("no active plan")
        return 1
    complete, total, current = phase_status(root)
    verified, detail = verify_attestation(root)
    print(f"plan: {directory.relative_to(root) if directory != root else '.'}")
    print(f"phases: {complete}/{total}")
    print(f"current: {current or 'none'}")
    print(f"attestation: {'valid' if verified else detail}")
    return 0


def command_attest(args: argparse.Namespace) -> int:
    root = find_project_root()
    if args.show:
        valid, detail = verify_attestation(root)
        print(f"{'valid' if valid else 'invalid'}: {detail}")
        return 0 if valid else 1
    print(attest(root, clear=args.clear))
    return 0


def _human_bytes(value: float) -> str:
    negative = value < 0
    amount = abs(float(value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024 or candidate == units[-1]:
            break
        amount /= 1024
    return f"{'-' if negative else ''}{amount:.2f} {unit}"


def _print_io_audit(result) -> None:
    first, last = result.snapshots[0], result.snapshots[-1]
    print("Codex local I/O audit")
    print(f"database: {result.database}")
    print(f"filesystem: {result.filesystem}")
    print(f"codex active: {'yes' if result.processes else 'no'}")
    for process in result.processes:
        print(f"  pid={process.pid} {process.command}")
    print(f"samples: {len(result.snapshots)} over {result.duration_seconds:.2f}s")
    print(f"WAL: {_human_bytes(first.wal_bytes)} -> {_human_bytes(last.wal_bytes)}")
    print(f"WAL growth: {_human_bytes(result.wal_growth_bytes)} ({_human_bytes(result.wal_bytes_per_second)}/s)")
    print(f"MAX(id) growth: {result.max_id_growth if result.max_id_growth is not None else 'unknown'}")
    print(f"id rate: {result.ids_per_second:.2f}/s" if result.ids_per_second is not None else "id rate: unknown")
    print(f"row count: {last.row_count if last.row_count is not None else 'not sampled'}")
    print(f"TRACE rows: {last.trace_count if last.trace_count is not None else 'not sampled'}")
    print(f"guard trigger: {'installed' if last.trigger_installed else 'not installed'}")
    if last.query_error:
        print(f"query warning: {last.query_error}")
    print(f"risk: {result.risk}")


def command_codex_io_audit(args: argparse.Namespace) -> int:
    result = audit_codex_io(args.codex_home, samples=args.samples, interval=args.interval, include_counts=args.details)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        _print_io_audit(result)
    return 0


def _maintenance_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "backup_root": Path(args.backup_dir).expanduser().absolute() if args.backup_dir else None,
        "max_backup_bytes": args.max_backup_bytes,
        "max_backup_total_bytes": args.max_backup_total_bytes,
        "max_backup_count": args.max_backup_count,
        "full_integrity_check": args.full_integrity_check,
    }


def _require_experimental_ack(args: argparse.Namespace) -> bool:
    if not (args.experimental and args.accept_diagnostic_loss):
        print(
            "error: applying the SQLite trigger is experimental and suppresses local diagnostic logs; "
            "pass --experimental --accept-diagnostic-loss together with --apply",
            file=sys.stderr,
        )
        return False
    return True


def command_codex_io_guard(args: argparse.Namespace) -> int:
    home = resolve_codex_home(args.codex_home)
    if not args.apply:
        snapshot = take_snapshot(home)
        print("dry-run: no database changes were made")
        print(f"database: {home / 'logs_2.sqlite'}")
        print(f"codex active: {'yes' if find_codex_processes() else 'no'}")
        print(f"WAL: {_human_bytes(snapshot.wal_bytes)}")
        print(f"guard trigger: {'installed' if snapshot.trigger_installed else 'not installed'}")
        print("apply requires: --apply --experimental --accept-diagnostic-loss")
        return 0
    if not _require_experimental_ack(args):
        return 2
    result = apply_log_guard(home, **_maintenance_kwargs(args))
    print(f"guard installed: {result.database}")
    print(f"backup: {result.backup_dir}")
    print(f"status: {result.status}")
    print(f"checkpoint: busy={result.checkpoint_busy} frames={result.checkpoint_frames} checkpointed={result.checkpointed_frames}")
    return 0 if result.status == "completed" else 1


def command_codex_io_restore(args: argparse.Namespace) -> int:
    home = resolve_codex_home(args.codex_home)
    if not args.apply:
        snapshot = take_snapshot(home)
        print("dry-run: no database changes were made")
        print(f"database: {home / 'logs_2.sqlite'}")
        print(f"guard trigger: {'installed' if snapshot.trigger_installed else 'not installed'}")
        print("restore requires: --apply --experimental --accept-diagnostic-loss")
        return 0
    if not _require_experimental_ack(args):
        return 2
    result = restore_log_writes(home, **_maintenance_kwargs(args))
    print(f"normal log writes restored: {result.database}")
    print(f"backup: {result.backup_dir}")
    print(f"status: {result.status}")
    print(f"checkpoint: busy={result.checkpoint_busy} frames={result.checkpoint_frames} checkpointed={result.checkpointed_frames}")
    return 0 if result.status == "completed" else 1


def _add_maintenance_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--experimental", action="store_true")
    parser.add_argument("--accept-diagnostic-loss", action="store_true")
    parser.add_argument("--backup-dir")
    parser.add_argument("--max-backup-bytes", type=int, default=DEFAULT_MAX_BACKUP_BYTES)
    parser.add_argument("--max-backup-total-bytes", type=int, default=DEFAULT_MAX_BACKUP_TOTAL_BYTES)
    parser.add_argument("--max-backup-count", type=int, default=DEFAULT_MAX_BACKUP_COUNT)
    parser.add_argument("--full-integrity-check", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rulesctl", description="AI Rules Manager")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="initialize and compile a project")
    init.add_argument("--root", default=".")
    init.add_argument("--name", required=True)
    init.add_argument("--platform", default="debian", choices=["debian"])
    init.add_argument("--domain", action="append", default=[], choices=["infrastructure", "quantitative-research", "digital-products", "blockchain-analysis"])
    init.add_argument("--context-mode", default="minimal", choices=["minimal", "balanced", "strict"])
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)
    parser_validate = sub.add_parser("validate")
    parser_validate.set_defaults(func=command_validate)
    parser_compile = sub.add_parser("compile")
    parser_compile.add_argument("--target", default="all", choices=["all", "agents", "skill", "hooks"])
    parser_compile.set_defaults(func=command_compile)
    parser_list = sub.add_parser("list-rules")
    parser_list.set_defaults(func=command_list)
    parser_audit = sub.add_parser("audit")
    parser_audit.set_defaults(func=command_audit)
    parser_plan = sub.add_parser("plan-init")
    parser_plan.add_argument("title")
    parser_plan.set_defaults(func=command_plan_init)
    parser_status = sub.add_parser("plan-status")
    parser_status.set_defaults(func=command_plan_status)
    parser_attest = sub.add_parser("attest")
    group = parser_attest.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true")
    group.add_argument("--clear", action="store_true")
    parser_attest.set_defaults(func=command_attest)
    parser_io = sub.add_parser("codex-io-audit")
    parser_io.add_argument("--codex-home")
    parser_io.add_argument("--samples", type=int, default=2)
    parser_io.add_argument("--interval", type=float, default=15.0)
    parser_io.add_argument("--details", action="store_true")
    parser_io.add_argument("--json", action="store_true")
    parser_io.set_defaults(func=command_codex_io_audit)
    parser_guard = sub.add_parser("codex-io-guard")
    _add_maintenance_args(parser_guard)
    parser_guard.set_defaults(func=command_codex_io_guard)
    parser_restore = sub.add_parser("codex-io-restore")
    _add_maintenance_args(parser_restore)
    parser_restore.set_defaults(func=command_codex_io_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, RuntimeError, UnsafePathError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
