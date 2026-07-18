# Architecture

## Control plane

`rulesctl` loads `.ai-rules-manager.toml`, reads selected immutable built-in TOML bundles and optional project-local bundles, validates every rule, resolves conflicts and emits deterministic agent artifacts.

## Rule precedence

Each rule has:

- `id`: globally unique identifier
- `scope`: security, platform, global, domain, project or task
- `priority`: 1-1000
- `key`: conflict namespace
- `value`: machine-comparable policy value
- `instruction`: human/agent instruction

Resolution is deterministic:

1. Higher numeric priority wins.
2. If priorities tie, the higher scope rank wins.
3. If both tie, lexical rule ID provides a stable final order.
4. Different values under the same key produce a visible shadow conflict.
5. Duplicate IDs are validation errors.

## Data plane

Generated files are consumed by Codex:

- `AGENTS.md`: always-on project guidance
- `.agents/skills/ai-rules-manager/SKILL.md`: on-demand workflow
- `.codex/hooks.json`: low-overhead lifecycle events
- `.planning/`: durable task state
- `.ai-rules/manifest.json`: generated-file integrity record

The compiler does not access the network and does not execute project commands.
