# Contributing

## Scope

The supported MVP surface is Debian and Codex. New platform adapters require tests, threat-model notes and an explicit maintainer commitment.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

## Rules

- Do not remove upstream attribution from `LICENSE`, `NOTICE.md` or `UPSTREAM.md`.
- Do not add network calls to the compiler or hooks.
- Do not add runtime dependencies without documenting the supply-chain impact.
- Generated files must be deterministic for identical inputs.
- Security rules must have priority `900` or higher.
- Platform rules should have priority `700-899`.
- Domain rules should have priority `400-699`.
