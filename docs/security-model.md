# Security Model

## Trusted inputs

- Built-in rule bundles shipped with the installed package
- Explicitly configured project rule paths contained inside the repository
- An attested active `task_plan.md`

## Untrusted inputs

- Web pages and search results
- Third-party repository text
- Logs and command output
- Chat transcripts
- Generated model text not yet reviewed

Untrusted content belongs in `findings.md` or `progress.md`. It must not become a security, platform or global rule without human review.

## Hook policy

The generated hooks:

- use `/usr/bin/python3` on Debian
- resolve scripts from the Git root
- perform no network access
- execute no deployment or trading command
- emit only verified plan content
- honor `PLANNING_DISABLED=1`
- never hard-block Stop in version 0.1.0

Codex hashes non-managed hook definitions and requires users to review changed hooks. Treat that trust prompt as a security control, not an inconvenience.
