# Changelog

## 0.1.0 - 2026-07-18

### Added

- Independent `ai-rules-manager` Python package and `rulesctl` CLI
- TOML rule bundles with deterministic priority resolution
- Debian, security, infrastructure, quantitative research, digital products and blockchain-analysis bundles
- Codex `AGENTS.md`, repository Skill and lifecycle hook compiler
- Persistent isolated plan directories and SHA-256 attestation
- Secret, prompt-injection, symlink, hook and manifest audit checks
- Read-only `rulesctl codex-io-audit` sampling for `logs_2.sqlite`, WAL growth, `MAX(id)`, TRACE rows and active Codex processes
- Explicit offline `codex-io-guard --apply` and `codex-io-restore --apply` with process gates, full sidecar backup, integrity validation and WAL checkpoint/truncate
- Codex local I/O safety rules covering active-database mutation, hook frequency, hook resource budgets, repository inventory reuse and explicit maintenance
- Unit and integration tests

### Changed

- Replaced the upstream multi-IDE planning plugin architecture with a Debian-first Codex control layer
- Replaced legacy `.codex/skills` output with current `.agents/skills` repository discovery
- Defaulted to low-overhead `minimal` context mode
- Minimal mode now generates only `SessionStart` and `PreCompact`; `UserPromptSubmit` is opt-in through balanced/strict mode and `Stop` is strict-only
- Generated hook timeouts are limited to one second and injected plan context is capped at 3,000 characters
- Hook project-root detection no longer spawns `git` during each hook execution

### Removed

- Upstream marketing copy and release metadata
- Unsupported Windows, Pi, Kiro, Hermes, OpenCode and other IDE adapters
- Automatic hard-stop completion gates
- Unreviewed cross-platform shell and PowerShell hook surfaces
