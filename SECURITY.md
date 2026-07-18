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

## Reporting

Report suspected vulnerabilities through GitHub Private Vulnerability Reporting. Do not include live credentials in a report.

## Operational requirements

- Review project hooks in Codex with `/hooks` before trusting them.
- Never copy untrusted web content into `task_plan.md` or rule bundles.
- Run `rulesctl audit` before committing generated files.
- Rotate any credential detected by the auditor; removing it from the latest commit is not sufficient if it entered Git history.
- Keep `PLANNING_DISABLED=1` on one-shot CI or read-only Codex runs that must not inherit an active project plan.
