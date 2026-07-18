# Changelog

## 0.1.0 - 2026-07-18

### Added

- Independent `ai-rules-manager` Python package and `rulesctl` CLI
- TOML rule bundles with deterministic priority resolution
- Debian, security, infrastructure, quantitative research, digital products and blockchain-analysis bundles
- Codex `AGENTS.md`, repository Skill and lifecycle hook compiler
- Persistent isolated plan directories and repository-external HMAC-SHA256 attestation
- Secret, prompt-injection, symlink, hook and manifest audit checks
- Atomic generated-file writes with symlink and repository-boundary enforcement
- Read-only `rulesctl codex-io-audit` sampling for `logs_2.sqlite`, WAL growth, `MAX(id)`, optional detailed row/TRACE counts, filesystem identity and active Codex processes
- Experimental offline `codex-io-guard` and `codex-io-restore` with triple acknowledgement, local-filesystem gates, exclusive locking, repeated process checks, bounded backups, reflink preference, ownership checks, SQLite validation and explicit partial-success states
- Codex safety rules covering active-database mutation, repository scope, destructive commands, sandbox defaults, hook frequency, process budgets and explicit maintenance
- Unit and integration tests for path escape, HMAC tampering, NFS refusal, backup limits, trigger restore and no-op compilation

### Changed

- Replaced the upstream multi-IDE planning plugin architecture with a Debian-first Codex control layer
- Replaced legacy `.codex/skills` output with current `.agents/skills` repository discovery
- Defaulted to low-overhead `minimal` context mode
- Minimal mode generates only `SessionStart` and `PreCompact`; `UserPromptSubmit` is opt-in through balanced/strict mode and `Stop` is strict-only
- Generated hook timeouts are limited to one second and injected plan context is capped at 3,000 characters
- Hooks inject only structured goal, phase and decision JSON after HMAC verification instead of complete Markdown plans
- Codex I/O audit defaults to file-size and indexed `MAX(id)` sampling; full row and TRACE counts require `--details`
- Repository audit performs one bounded traversal and skips dependencies, build output, caches, data, backups, models and checkpoints
- Unchanged generated files are not rewritten, reducing unnecessary filesystem writes
- CI pins Debian container digests and `actions/checkout` to immutable identifiers and treats Python resource warnings as test failures

### Removed

- Plain repository-local SHA-256 plan attestations as a security trust mechanism
- Upstream marketing copy and release metadata
- Unsupported Windows, Pi, Kiro, Hermes, OpenCode and other IDE adapters
- Automatic hard-stop completion gates
- Unreviewed cross-platform shell and PowerShell hook surfaces
