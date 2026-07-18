from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

TRIGGER_NAME = "ai_rules_manager_block_log_inserts"
DATABASE_NAME = "logs_2.sqlite"
SIDECAR_SUFFIXES = ("", "-wal", "-shm")


class CodexActiveError(RuntimeError):
    """Raised when offline maintenance is requested while Codex is running."""


@dataclass(frozen=True)
class CodexProcess:
    pid: int
    command: str


@dataclass(frozen=True)
class IOSnapshot:
    captured_at: float
    database_bytes: int
    wal_bytes: int
    shm_bytes: int
    max_id: int | None
    row_count: int | None
    trace_count: int | None
    trigger_installed: bool
    query_error: str | None = None


@dataclass(frozen=True)
class IOAuditResult:
    codex_home: Path
    database: Path
    processes: tuple[CodexProcess, ...]
    snapshots: tuple[IOSnapshot, ...]
    wal_growth_bytes: int
    max_id_growth: int | None
    duration_seconds: float
    wal_bytes_per_second: float
    ids_per_second: float | None
    risk: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["codex_home"] = str(self.codex_home)
        data["database"] = str(self.database)
        data["processes"] = [asdict(item) for item in self.processes]
        data["snapshots"] = [asdict(item) for item in self.snapshots]
        return data


@dataclass(frozen=True)
class MaintenanceResult:
    database: Path
    backup_dir: Path
    trigger_installed: bool
    checkpoint_busy: int
    checkpoint_frames: int
    checkpointed_frames: int


ProcessDetector = Callable[[], list[CodexProcess]]


def resolve_codex_home(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
    return Path(configured).expanduser().resolve()


def database_path(codex_home: str | Path | None = None) -> Path:
    return resolve_codex_home(codex_home) / DATABASE_NAME


def _read_proc_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def find_codex_processes(proc_root: Path = Path("/proc")) -> list[CodexProcess]:
    """Find Codex/app-server processes without spawning pgrep or ps."""
    found: list[CodexProcess] = []
    own_pid = os.getpid()
    if not proc_root.is_dir():
        return found

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == own_pid:
            continue
        comm = _read_proc_text(entry / "comm")
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            raw = b""
        tokens = [item.decode("utf-8", errors="replace") for item in raw.split(b"\0") if item]
        executable = Path(tokens[0]).name.lower() if tokens else ""
        comm_lower = comm.lower()
        token_names = {Path(token).name.lower() for token in tokens}
        joined = " ".join(tokens)

        is_codex = (
            comm_lower in {"codex", "codex-app-server", "codex desktop"}
            or executable in {"codex", "codex-app-server"}
            or "codex-app-server" in token_names
            or ("app-server" in token_names and any(Path(token).name.lower() == "codex" for token in tokens))
        )
        if is_codex:
            found.append(CodexProcess(pid=pid, command=joined or comm or "codex"))
    return sorted(found, key=lambda item: item.pid)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    connection.execute("PRAGMA query_only = ON")
    return connection


def take_snapshot(
    codex_home: str | Path | None = None, *, include_counts: bool = False
) -> IOSnapshot:
    db = database_path(codex_home)
    if not db.is_file():
        raise FileNotFoundError(db)

    max_id: int | None = None
    row_count: int | None = None
    trace_count: int | None = None
    trigger_installed = False
    query_error: str | None = None

    try:
        with _readonly_connection(db) as connection:
            trigger_installed = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?)",
                (TRIGGER_NAME,),
            ).fetchone()[0] == 1
            table_exists = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs')"
            ).fetchone()[0] == 1
            if table_exists:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(logs)")}
                if "id" in columns:
                    max_id = connection.execute("SELECT MAX(id) FROM logs").fetchone()[0]
                if include_counts:
                    row_count = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
                    if "level" in columns:
                        trace_count = connection.execute(
                            "SELECT COUNT(*) FROM logs WHERE UPPER(CAST(level AS TEXT)) = 'TRACE'"
                        ).fetchone()[0]
    except sqlite3.Error as exc:
        query_error = str(exc)

    return IOSnapshot(
        captured_at=time.time(),
        database_bytes=_file_size(db),
        wal_bytes=_file_size(Path(f"{db}-wal")),
        shm_bytes=_file_size(Path(f"{db}-shm")),
        max_id=max_id,
        row_count=row_count,
        trace_count=trace_count,
        trigger_installed=trigger_installed,
        query_error=query_error,
    )


def _risk_level(wal_rate: float, id_rate: float | None, query_errors: Iterable[str | None]) -> str:
    if any(query_errors):
        return "unknown"
    if wal_rate >= 1024 * 1024 or (id_rate is not None and id_rate >= 100):
        return "critical"
    if wal_rate > 0 or (id_rate is not None and id_rate > 0):
        return "warning"
    return "normal"


def audit_codex_io(
    codex_home: str | Path | None = None,
    *,
    samples: int = 2,
    interval: float = 15.0,
    process_detector: ProcessDetector = find_codex_processes,
    sleeper: Callable[[float], None] = time.sleep,
    include_counts: bool = False,
) -> IOAuditResult:
    if samples < 1 or samples > 10:
        raise ValueError("samples must be between 1 and 10")
    if interval < 0 or interval > 300:
        raise ValueError("interval must be between 0 and 300 seconds")

    home = resolve_codex_home(codex_home)
    captured: list[IOSnapshot] = []
    for index in range(samples):
        captured.append(take_snapshot(home, include_counts=include_counts))
        if index + 1 < samples:
            sleeper(interval)

    first = captured[0]
    last = captured[-1]
    duration = max(0.0, last.captured_at - first.captured_at)
    wal_growth = last.wal_bytes - first.wal_bytes
    id_growth = None
    if first.max_id is not None and last.max_id is not None:
        id_growth = last.max_id - first.max_id
    denominator = duration if duration > 0 else 1.0
    wal_rate = wal_growth / denominator
    id_rate = id_growth / denominator if id_growth is not None else None
    risk = _risk_level(wal_rate, id_rate, (item.query_error for item in captured))

    return IOAuditResult(
        codex_home=home,
        database=database_path(home),
        processes=tuple(process_detector()),
        snapshots=tuple(captured),
        wal_growth_bytes=wal_growth,
        max_id_growth=id_growth,
        duration_seconds=duration,
        wal_bytes_per_second=wal_rate,
        ids_per_second=id_rate,
        risk=risk,
    )


def _require_idle(process_detector: ProcessDetector) -> None:
    processes = process_detector()
    if processes:
        detail = "; ".join(f"pid={item.pid} {item.command}" for item in processes)
        raise CodexActiveError(
            "active Codex process detected; no database changes were made. "
            "Save work, close Codex Desktop/CLI/IDE integrations, then retry. " + detail
        )


def _backup_database(db: Path, operation: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = db.parent / "backups" / f"logs-2-{operation}-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    copied: list[str] = []
    for suffix in SIDECAR_SUFFIXES:
        source = Path(f"{db}{suffix}")
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)
            copied.append(source.name)
    metadata = {
        "schema": 1,
        "operation": operation,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(db),
        "files": copied,
    }
    (backup_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return backup_dir


def _validate_database(connection: sqlite3.Connection) -> None:
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError("database integrity check failed: " + "; ".join(integrity))
    table_exists = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs')"
    ).fetchone()[0]
    if table_exists != 1:
        raise RuntimeError("logs table not found; Codex database schema may have changed")


def _checkpoint(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError("unexpected wal_checkpoint result")
    return int(row[0]), int(row[1]), int(row[2])


def apply_log_guard(
    codex_home: str | Path | None = None,
    *,
    process_detector: ProcessDetector = find_codex_processes,
) -> MaintenanceResult:
    _require_idle(process_detector)
    db = database_path(codex_home)
    if not db.is_file():
        raise FileNotFoundError(db)
    backup_dir = _backup_database(db, "guard")

    try:
        with sqlite3.connect(db, timeout=5.0) as connection:
            _validate_database(connection)
            connection.execute(
                f'''CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAME}
                    BEFORE INSERT ON logs
                    BEGIN
                        SELECT RAISE(IGNORE);
                    END'''
            )
            connection.commit()
            checkpoint = _checkpoint(connection)
    except Exception as exc:
        raise RuntimeError(f"guard failed; untouched backup is available at {backup_dir}") from exc

    return MaintenanceResult(
        database=db,
        backup_dir=backup_dir,
        trigger_installed=True,
        checkpoint_busy=checkpoint[0],
        checkpoint_frames=checkpoint[1],
        checkpointed_frames=checkpoint[2],
    )


def restore_log_writes(
    codex_home: str | Path | None = None,
    *,
    process_detector: ProcessDetector = find_codex_processes,
) -> MaintenanceResult:
    _require_idle(process_detector)
    db = database_path(codex_home)
    if not db.is_file():
        raise FileNotFoundError(db)
    backup_dir = _backup_database(db, "restore")

    try:
        with sqlite3.connect(db, timeout=5.0) as connection:
            _validate_database(connection)
            connection.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME}")
            connection.commit()
            checkpoint = _checkpoint(connection)
    except Exception as exc:
        raise RuntimeError(f"restore failed; untouched backup is available at {backup_dir}") from exc

    return MaintenanceResult(
        database=db,
        backup_dir=backup_dir,
        trigger_installed=False,
        checkpoint_busy=checkpoint[0],
        checkpoint_frames=checkpoint[1],
        checkpointed_frames=checkpoint[2],
    )
