# Codex Local I/O Protection

AI Rules Manager treats Codex internal SQLite maintenance as a separate, explicit, offline operation. Normal project initialization, rule compilation, planning, testing and deployment workflows never modify `CODEX_HOME`.

## Development-time audit

Run a read-only two-sample audit while Codex is active:

```bash
rulesctl codex-io-audit
```

Defaults:

- database: `${CODEX_HOME:-$HOME/.codex}/logs_2.sqlite`
- samples: 2
- interval: 15 seconds
- database connection: SQLite `mode=ro` plus `PRAGMA query_only=ON`
- fast path: file sizes plus indexed `MAX(id)` only
- no checkpoint, vacuum, trigger, process termination or background monitor

Custom sampling:

```bash
rulesctl codex-io-audit --samples 3 --interval 10
rulesctl codex-io-audit --details
rulesctl codex-io-audit --json
rulesctl codex-io-audit --codex-home /home/night/.codex
```

The default audit reports Codex processes, WAL growth, `MAX(id)` growth, guard status and a risk level. `--details` additionally runs full row and TRACE counts and should be used only when that extra scan is needed. A critical result does not stop the active development session.

## Dry-run maintenance check

The guard and restore commands are non-mutating unless `--apply` is present:

```bash
rulesctl codex-io-guard
rulesctl codex-io-restore
```

## Apply the temporary log guard

Only after saving work and fully closing Codex Desktop, CLI, app-server, IDE integrations and remote-control sessions:

```bash
rulesctl codex-io-guard --apply
```

The command refuses to continue when a Codex process is detected. When idle, it:

1. copies `logs_2.sqlite`, `logs_2.sqlite-wal` and `logs_2.sqlite-shm` when present;
2. writes backup metadata under `$CODEX_HOME/backups/`;
3. runs `PRAGMA integrity_check`;
4. verifies that the `logs` table still exists;
5. creates the `ai_rules_manager_block_log_inserts` trigger;
6. executes `PRAGMA wal_checkpoint(TRUNCATE)`;
7. reports the checkpoint result.

This is a reversible emergency mitigation. It suppresses local persistent log inserts and can reduce diagnostic data available for troubleshooting. It is not automatically applied by any project rule or hook.

## Restore normal local logging

After fully closing Codex:

```bash
rulesctl codex-io-restore --apply
```

The restore operation creates another backup, validates the database, removes only the AI Rules Manager trigger and truncates the WAL. It does not replace the database from an older backup.

## Hook budget

Generated hooks use the following policy:

| Context mode | Generated events |
|---|---|
| `minimal` | `SessionStart`, `PreCompact` |
| `balanced` | minimal plus `UserPromptSubmit` |
| `strict` | balanced plus non-blocking `Stop` advisory |

All generated commands have a one-second timeout. Plan context is limited to 3,000 characters. Hooks do not inspect `CODEX_HOME`, launch SQLite, start background processes or recursively scan the repository.

## Important boundaries

- `logs_2.sqlite` is treated separately from state/session databases such as `state_5.sqlite`.
- Windows Codex Desktop and WSL may use different home directories; pass the actual `--codex-home` explicitly.
- Process detection in version 0.1.0 targets Debian/Linux `/proc` and cannot see native Windows processes from inside WSL.
- Codex updates may recreate or migrate the database. Re-run the read-only audit and remove the trigger after an official fix is verified.
