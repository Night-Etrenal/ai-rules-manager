from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import audit_project, write_report
from .compiler import compile_project
from .config import CONFIG_NAME, available_bundles, find_project_root, load_config, load_rules
from .planning import attest, create_plan, phase_status, resolve_plan_dir, verify_attestation
from .resolver import resolve_rules
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
    (root / CONFIG_NAME).write_text(content, encoding="utf-8")


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_NAME
    if config_path.exists() and not args.force:
        print(f"error: {config_path} already exists; use --force", file=sys.stderr)
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
    try:
        config, rules, resolution = _loaded()
        errors = validate(config, rules, resolution)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    for conflict in resolution.conflicts:
        shadowed = ", ".join(item.id for item in conflict.shadowed)
        print(f"warning: {conflict.key}: {conflict.winner.id} shadows {shadowed}")
    print(f"valid: {len(resolution.active)} active rules")
    return 0


def command_compile(args: argparse.Namespace) -> int:
    config, rules, resolution = _loaded()
    errors = validate(config, rules, resolution)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    written = compile_project(config, resolution, args.target)
    for path in written:
        print(path.relative_to(config.root))
    return 0


def command_list(_: argparse.Namespace) -> int:
    try:
        config, _, resolution = _loaded()
        for rule in resolution.active:
            print(f"{rule.priority:04d} {rule.scope:8s} {rule.id} = {rule.value}")
        if resolution.conflicts:
            print("\nResolved conflicts:")
            for conflict in resolution.conflicts:
                print(f"- {conflict.key}: winner={conflict.winner.id}")
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
        print(f"error: plan already exists: {exc.filename}", file=sys.stderr)
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
    try:
        result = attest(root, clear=args.clear)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rulesctl", description="AI Rules Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize and compile a project")
    init.add_argument("--root", default=".")
    init.add_argument("--name", required=True)
    init.add_argument("--platform", default="debian", choices=["debian"])
    init.add_argument("--domain", action="append", default=[], choices=[
        "infrastructure", "quantitative-research", "digital-products", "blockchain-analysis"
    ])
    init.add_argument("--context-mode", default="minimal", choices=["minimal", "balanced", "strict"])
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    validate_parser = sub.add_parser("validate", help="validate config and rule registry")
    validate_parser.set_defaults(func=command_validate)

    compile_parser = sub.add_parser("compile", help="compile agent outputs")
    compile_parser.add_argument("--target", default="all", choices=["all", "agents", "skill", "hooks"])
    compile_parser.set_defaults(func=command_compile)

    list_parser = sub.add_parser("list-rules", help="list active rules or available bundles")
    list_parser.set_defaults(func=command_list)

    audit_parser = sub.add_parser("audit", help="audit trusted files, hooks and generated manifest")
    audit_parser.set_defaults(func=command_audit)

    plan_init = sub.add_parser("plan-init", help="create and activate an isolated plan")
    plan_init.add_argument("title")
    plan_init.set_defaults(func=command_plan_init)

    status = sub.add_parser("plan-status", help="show active plan state")
    status.set_defaults(func=command_plan_status)

    attest_parser = sub.add_parser("attest", help="write or verify plan SHA-256 attestation")
    group = attest_parser.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true")
    group.add_argument("--clear", action="store_true")
    attest_parser.set_defaults(func=command_attest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
