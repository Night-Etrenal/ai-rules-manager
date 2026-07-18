# Migration from planning-with-files

This repository is not a drop-in namespace rename.

## Removed

- `.claude-plugin` packaging and Claude slash commands
- Cross-platform IDE mirrors
- Legacy `.codex/skills` placement
- Automatic completion blocking
- Per-tool plan recitation by default

## New equivalents

| Previous concept | AI Rules Manager |
|---|---|
| `task_plan.md` | `.planning/<id>/task_plan.md` |
| active plan resolver | `.planning/.active_plan` |
| plan attestation | `rulesctl attest` |
| skill instructions | `.agents/skills/ai-rules-manager/SKILL.md` |
| plan injection hooks | generated `.codex/hooks.json` |
| static instructions | generated `AGENTS.md` |
| manual policy text | TOML rule registry and compiler |

Before migration, remove old project hooks or global hooks to avoid duplicate lifecycle messages.
