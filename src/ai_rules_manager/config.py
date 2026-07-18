from __future__ import annotations

import os
import tomllib
from importlib import resources
from pathlib import Path

from .models import ProjectConfig, Rule
from .safe_fs import UnsafePathError, safe_regular_file

CONFIG_NAME = ".ai-rules-manager.toml"
MAX_EXTRA_RULE_FILES = 1000
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", "target", "coverage", "__pycache__"}


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        config = candidate / CONFIG_NAME
        git = candidate / ".git"
        if config.is_file() or git.exists():
            return candidate
    return current


def load_config(root: Path | None = None) -> ProjectConfig:
    project_root = find_project_root(root)
    path = safe_regular_file(project_root, CONFIG_NAME)
    assert path is not None
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    selection = data.get("selection", {})
    output = data.get("output", {})
    return ProjectConfig(
        root=project_root,
        name=str(project.get("name", "")).strip(),
        platform=str(project.get("platform", "")).strip(),
        domains=[str(item) for item in project.get("domains", [])],
        context_mode=str(project.get("context_mode", "minimal")).strip(),
        bundles=[str(item) for item in selection.get("bundles", [])],
        extra_rule_paths=[str(item) for item in selection.get("extra_rule_paths", [])],
        targets=[str(item) for item in output.get("targets", ["all"])],
    )


def _bundle_root():
    return resources.files("ai_rules_manager").joinpath("bundles")


def available_bundles() -> list[str]:
    base = _bundle_root()
    result: list[str] = []
    for path in base.iterdir():
        if path.is_file() and path.name.endswith(".toml"):
            result.append(path.name.removesuffix(".toml"))
        elif path.is_dir():
            for nested in path.iterdir():
                if nested.is_file() and nested.name.endswith(".toml"):
                    result.append(f"{path.name}/{nested.name.removesuffix('.toml')}")
    return sorted(result)


def _read_rule_document(path, source: str) -> list[Rule]:
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError(f"{source}: rule file exceeds 1 MiB")
    data = tomllib.loads(raw.decode("utf-8"))
    blocks = data.get("rules", [])
    if not isinstance(blocks, list):
        raise ValueError(f"{source}: [[rules]] array is required")
    return [Rule.from_mapping(item, source) for item in blocks]


def _iter_extra_rule_files(root: Path, configured: str) -> list[Path]:
    relative = Path(configured)
    if relative.is_absolute() or ".." in relative.parts:
        raise UnsafePathError(f"unsafe extra rule path: {configured}")
    lexical = root / relative
    if not lexical.exists():
        raise FileNotFoundError(lexical)
    if lexical.is_symlink():
        raise UnsafePathError(f"extra rule path is a symlink: {configured}")
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise UnsafePathError(f"extra rule path escapes project root: {configured}") from exc
    if resolved.is_file():
        if resolved.suffix != ".toml":
            raise ValueError(f"extra rule file must end in .toml: {configured}")
        return [resolved]
    if not resolved.is_dir():
        raise ValueError(f"extra rule path is not a regular file or directory: {configured}")

    result: list[Path] = []
    for current, dirs, files in os.walk(resolved, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in list(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                raise UnsafePathError(f"symlink inside extra rule directory: {candidate}")
        for name in files:
            candidate = current_path / name
            if candidate.is_symlink():
                raise UnsafePathError(f"symlink extra rule file: {candidate}")
            if candidate.suffix == ".toml":
                result.append(candidate)
                if len(result) > MAX_EXTRA_RULE_FILES:
                    raise ValueError(f"extra rule path exceeds {MAX_EXTRA_RULE_FILES} TOML files")
    return sorted(result)


def load_rules(config: ProjectConfig) -> list[Rule]:
    base = _bundle_root()
    rules: list[Rule] = []
    for bundle in config.bundles:
        parts = bundle.split("/")
        if not parts or any(not part or part in {".", ".."} for part in parts):
            raise ValueError(f"invalid bundle name: {bundle}")
        relative = Path(*parts).with_suffix(".toml")
        resource = base.joinpath(str(relative))
        if not resource.is_file():
            raise FileNotFoundError(f"unknown rule bundle: {bundle}")
        rules.extend(_read_rule_document(resource, f"builtin:{bundle}"))

    for configured in config.extra_rule_paths:
        for candidate in _iter_extra_rule_files(config.root, configured):
            rules.extend(_read_rule_document(candidate, str(candidate.relative_to(config.root))))
    return rules
