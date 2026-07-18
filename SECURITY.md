# Security Policy

## Supported versions

Only the latest tagged release is supported.

## Threat model

AI Rules Manager creates files that may be loaded into an AI agent's developer context and installs project-local lifecycle hooks. Relevant threats include:

- Prompt injection in trusted planning or rule files
- Secrets copied into generated context
- Symlink or path traversal escaping the repository
- Unreviewed hook commands
- Rule precedence manipulation
- Manifest tampering
- Destructive shell or Git commands executed with broad Codex permissions
- Codex local SQLite write amplification, corruption or unsupported direct modification
- Network/shared filesystem use with SQLite WAL
- Unbounded repository traversal, child processes, CPU, memory or disk use
- Sensitive prompts, tool output and local paths copied into Codex diagnostic logs or backups

## Security boundaries

AI Rules Manager can harden its own generated files, hooks and maintenance commands. It cannot repair defects inside Codex Desktop, Codex CLI, app-server, Electron, operating-system sandboxing or Codex-managed worktree cleanup.

`AGENTS.md`, Skills and rule text are policy guidance, not an operating-system security boundary. Use Codex sandboxing, approval prompts, filesystem permissions, Git commits, tested backups and least privilege as the primary controls.

## Reporting

Report suspected vulnerabilities through GitHub Private Vulnerability Reporting. Do not include live credentials, raw Codex databases, full session JSONL files, private repository names or unsanitized local paths in a public report.

## Operational requirements

- Review project hooks in Codex with `/hooks` before trusting them.
- Default Codex to `workspace-write` with on-request approval; do not use `danger-full-access` as a normal profile.
- Never copy untrusted web content into `task_plan.md` or rule bundles.
- Run `rulesctl audit` before committing generated files.
- Rotate any credential detected by the auditor; removing it from the latest commit is not sufficient if it entered Git history.
- Keep `PLANNING_DISABLED=1` on one-shot CI or read-only Codex runs that must not inherit an active project plan.
- Keep `CODEX_HOME` on a per-machine local filesystem. Do not place it on NFS, SMB/CIFS, SSHFS, 9p, DrvFS or a multi-host shared home.
- Never run Codex SQLite maintenance while Codex Desktop, CLI, app-server, IDE integrations or remote-control sessions are active.
- Treat `codex-io-guard` as an experimental emergency mitigation. It requires `--apply --experimental --accept-diagnostic-loss` and suppresses diagnostic logs.
- Store Codex maintenance backups on a trusted local disk with sufficient capacity. Backup files can contain prompts, tool outputs, commands and local paths.
- Never run `rm -rf`, `git clean -fdx`, `git reset --hard`, recursive deletion or bulk replacement without a canonical target manifest and explicit action-time confirmation.
- Do not archive or delete Codex-managed worktrees until uncommitted work is separately backed up and the main checkout has been verified.

## Implemented controls

- Generated project files use atomic replacement and reject symlink targets or symlink parent directories.
- Extra rule files and plan files must remain inside the canonical repository root.
- Plan attestation uses HMAC-SHA256 with a 32-byte key outside the repository and mode `0600`.
- Hooks inject only bounded structured plan metadata, not the complete Markdown plan.
- Repository auditing performs one bounded traversal and skips generated, dependency, data, backup, model and cache directories.
- SQLite maintenance uses a local-filesystem gate, exclusive `flock`, repeated process checks, ownership checks, bounded backups, free-space checks, reflink when available, SQLite validation and explicit partial-success status.
- CI pins Debian container digests and `actions/checkout` to immutable identifiers.
