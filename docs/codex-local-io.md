# Codex Local I/O Protection

AI Rules Manager treats Codex internal SQLite maintenance as a separate, explicit, experimental and offline operation. Normal project initialization, rule compilation, planning, testing and deployment workflows never modify `CODEX_HOME`.

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

The default audit reports the detected filesystem, Codex processes, WAL growth, `MAX(id)` growth, guard status and a risk level. `--details` additionally runs full row and TRACE counts and should be used only when that extra scan is needed. A critical result does not stop the active development session.

## Dry-run maintenance check

The guard and restore commands are non-mutating unless all required acknowledgement flags are present:

```bash
rulesctl codex-io-guard
rulesctl codex-io-restore
```

## Apply the temporary log guard

Only after saving work and fully closing Codex Desktop, CLI, app-server, IDE integrations and remote-control sessions:

```bash
rulesctl codex-io-guard \
  --apply \
  --experimental \
  --accept-diagnostic-loss
```

The trigger suppresses local diagnostic inserts. It does not stop Codex from constructing TRACE events or attempting transactions, and it can reduce evidence available for troubleshooting. It is not an official OpenAI fix.

The command refuses to continue when:

- a Debian/Linux Codex or app-server process is detected;
- `CODEX_HOME` or a database sidecar is a symlink or is not owned by the current user;
- `CODEX_HOME` contains a symlink component;
- the filesystem is NFS, SMB/CIFS, SSHFS, 9p, DrvFS or a Windows mount such as `/mnt/c`;
- another maintenance process holds the exclusive lock;
- backup size, total backup budget, count or free-space limits would be exceeded;
- SQLite `quick_check` fails or the `logs` schema is not compatible.

When all gates pass, it:

1. acquires `$CODEX_HOME/.ai-rules-manager-maintenance.lock` with `flock`;
2. rechecks active Codex processes;
3. copies `logs_2.sqlite`, WAL and SHM when present, preferring filesystem reflink;
4. creates backup directories as `0700` and files as `0600`;
5. validates that source files did not change during backup;
6. rechecks active Codex processes;
7. runs `PRAGMA quick_check` by default, or full `integrity_check` with `--full-integrity-check`;
8. verifies the `logs` table and required `id` column;
9. creates `ai_rules_manager_block_log_inserts`;
10. commits the trigger and runs `PRAGMA wal_checkpoint(TRUNCATE)`;
11. reports whether the operation completed or the trigger committed while checkpoint remained busy.

Default backup budgets:

```text
single maintenance backup: 2 GiB
all retained maintenance backups: 8 GiB
backup directory count: 8
free-space safety margin: 64 MiB
```

Use another local disk when necessary:

```bash
rulesctl codex-io-guard \
  --apply --experimental --accept-diagnostic-loss \
  --backup-dir /srv/local-backups/codex
```

Explicit limits can be changed with `--max-backup-bytes`, `--max-backup-total-bytes` and `--max-backup-count`. Old backups are never deleted automatically.

## Restore normal local logging

After fully closing Codex:

```bash
rulesctl codex-io-restore \
  --apply \
  --experimental \
  --accept-diagnostic-loss
```

The restore operation creates another bounded backup, validates the database, removes only the AI Rules Manager trigger and truncates the WAL. It does not replace the database from an older backup.

## Hook budget and plan integrity

Generated hooks use the following policy:

| Context mode | Generated events |
|---|---|
| `minimal` | `SessionStart`, `PreCompact` |
| `balanced` | minimal plus `UserPromptSubmit` |
| `strict` | balanced plus non-blocking `Stop` advisory |

All generated commands have a one-second timeout. Plan context is limited to 3,000 characters and consists only of structured goal, phase and decision JSON. The plan is accepted only when its HMAC-SHA256 matches a 32-byte key stored outside the repository at `~/.config/ai-rules-manager/attestation.key` with mode `0600`.

Hooks do not inspect `CODEX_HOME`, launch SQLite, start background processes or recursively scan the repository.

## Important boundaries

- `logs_2.sqlite` is treated separately from state/session databases such as `state_5.sqlite`.
- The guard cannot remove Codex event formatting or queue CPU cost; it only suppresses persisted inserts.
- Windows Codex Desktop and WSL may use different home directories. Maintenance through `/mnt/c` is refused because WSL cannot see native Windows Codex processes reliably.
- Never put `CODEX_HOME` on NFS, SMB, SSHFS or a multi-host shared home while Codex uses SQLite WAL.
- Codex updates may recreate or migrate the database. Re-run the read-only audit and remove the trigger after an official fix is verified.
- Codex worktree cleanup, Full Access deletion, sandbox, child-process and internal logging defects are outside this repository's control. Use Git commits/backups and least-privilege Codex settings as the primary safety boundary.
