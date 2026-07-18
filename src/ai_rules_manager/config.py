from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

from .models import ProjectConfig, Rule

CONFIG_NAME = ".ai-rules-manager.toml"


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_NAME).is_file() or (candidate / ".git").exists():
            return candidate
    return current


def load_config(root: Path | None = None) -> ProjectConfig:
    project_root = find_project_root(root)
    path = project_root / CONFIG_NAME
    if not path.is_file():
        raise FileNotFoundError(f"{CONFIG_NAME} not found under {project_root}")
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
    data = tomllib.loads(raw.decode("utf-8"))
    blocks = data.get("rules", [])
    if not isinstance(blocks, list):
        raise ValueError(f"{source}: [[rules]] array is required")
    return [Rule.from_mapping(item, source) for item in blocks]


def load_rules(config: ProjectConfig) -> list[Rule]:
    base = _bundle_root()
    rules: list[Rule] = []
    for bundle in config.bundles:
        relative = Path(*bundle.split("/")).with_suffix(".toml")
        resource = base.joinpath(str(relative))
        if not resource.is_file():
            raise FileNotFoundError(f"unknown rule bundle: {bundle}")
        rules.extend(_read_rule_document(resource, f"builtin:{bundle}"))

    for configured in config.extra_rule_paths:
        path = (config.root / configured).resolve()
        try:
            path.relative_to(config.root.resolve())
        except ValueError as exc:
            raise ValueError(f"extra rule path escapes project root: {configured}") from exc
        candidates = sorted(path.rglob("*.toml")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            rules.extend(_read_rule_document(candidate, str(candidate.relative_to(config.root))))
    return rules
