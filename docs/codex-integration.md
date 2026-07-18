# Codex Integration

AI Rules Manager uses current Codex repository conventions:

- Project instructions: `AGENTS.md`
- Repository skills: `.agents/skills/<skill>/SKILL.md`
- Project hooks: `.codex/hooks.json`

Codex may be launched from a subdirectory, so hook commands resolve the Git root before loading scripts. Project hooks require repository trust and separate hook review.

## Installation into a project

```bash
pip install -e /path/to/ai-rules-manager
cd /path/to/project
rulesctl init --name project --platform debian --domain infrastructure
```

Open Codex, run `/hooks`, inspect each command and trust the generated hash.

## One-shot opt-out

```bash
PLANNING_DISABLED=1 codex exec -C /path/to/project "Review this branch"
```

This prevents a short read-only job from inheriting and mutating a long-running active plan.
