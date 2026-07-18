from __future__ import annotations

import errno
import fcntl
import json
import os
import shutil
import sqlite3
import stat
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

TRIGGER_NAME = "ai_rules_manager_block_log_inserts"
DATABASE_NAME = "logs_2.sqlite"
SIDECAR_SUFFIXES = ("", "-wal", "-shm")
DEFAULT_MAX_BACKUP_BYTES = 2 * 1024**3
DEFAULT_MAX_BACKUP_TOTAL_BYTES = 8 * 1024**3
DEFAULT_MAX_BACKUP_COUNT = 8
MIN_FREE_MARGIN_BYTES = 64 * 1024**2
UNSAFE_FILESYSTEMS = {"nfs", "nfs4", "cifs", "smb3", "9p", "drvfs", "sshfs", "fuse.sshfs"}
FICLONE = 0x40049409


class CodexActiveError(RuntimeError):
    pass


class UnsafeCodexHomeError(RuntimeError):
    pass


class MaintenanceBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexProcess:
    pid: int
    command: str


@dataclass(frozen=True)
class MountInfo:
    mount_point: Path
    filesystem: str


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
    filesystem: str
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
    status: str
    checkpoint_busy: int
    checkpoint_frames: int
    checkpointed_frames: int


ProcessDetector = Callable[[], list[CodexProcess]]
FilesystemDetector = Callable[[Path], MountInfo]


def resolve_codex_home(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("CODEX_HOME") or (Path.home() / ".codex")
    return Path(configured).expanduser().absolute()


def database_path(codex_home: str | Path | None = None) -> Path:
    return resolve_codex_home(codex_home) / DATABASE_NAME


def _read_proc_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def find_codex_processes(proc_root: Path = Path("/proc")) -> list[CodexProcess]:
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
        names = {Path(token).name.lower() for token in tokens}
        executable = Path(tokens[0]).name.lower() if tokens else ""
        comm_lower = comm.lower()
        is_codex = (
            comm_lower in {"codex", "codex-app-server", "codex desktop"}
            or executable in {"codex", "codex-app-server"}
            or "codex-app-server" in names
            or ("app-server" in names and "codex" in names)
        )
        if is_codex:
            found.append(CodexProcess(pid=pid, command=" ".join(tokens) or comm or "codex"))
    return sorted(found, key=lambda item: item.pid)


def _unescape_mount(value: str) -> str:
    return value.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def detect_mount(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> MountInfo:
    resolved = path.resolve(strict=False)
    best: tuple[int, MountInfo] | None = None
    try:
        lines = mountinfo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return MountInfo(Path("/"), "unknown")
    for line in lines:
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        fields = left.split()
        right_fields = right.split()
        if len(fields) < 5 or not right_fields:
            continue
        mount_point = Path(_unescape_mount(fields[4]))
        filesystem = right_fields[0].lower()
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        score = len(mount_point.parts)
        if best is None or score > best[0]:
            best = (score, MountInfo(mount_point, filesystem))
    return best[1] if best else MountInfo(Path("/"), "unknown")


def _validate_codex_home(home: Path, *, for_write: bool, filesystem_detector: FilesystemDetector) -> MountInfo:
    if not home.exists() or not home.is_dir():
        raise FileNotFoundError(home)
    resolved = home.resolve(strict=True)
    if resolved != home:
        raise UnsafeCodexHomeError(f"CODEX_HOME must not contain symlink components: {home}")
    info = home.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeCodexHomeError(f"CODEX_HOME must not be a symlink: {home}")
    mount = filesystem_detector(home)
    fs = mount.filesystem.lower()
    if for_write and (fs in UNSAFE_FILESYSTEMS or fs.startswith("fuse.sshfs")):
        raise UnsafeCodexHomeError(
            f"refusing SQLite maintenance on unsafe filesystem {fs!r} mounted at {mount.mount_point}"
        )
    if for_write and len(home.parts) >= 3 and home.parts[1] == "mnt" and len(home.parts[2]) == 1:
        raise UnsafeCodexHomeError(f"refusing SQLite maintenance on a Windows/foreign mount: {home}")
    return mount


def _regular_nofollow(path: Path, *, required: bool = True) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if required:
            raise
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafeCodexHomeError(f"expected regular non-symlink file: {path}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise PermissionError(f"file is not owned by current user: {path}")
    return info


def _file_size(path: Path) -> int:
    info = _regular_nofollow(path, required=False)
    return info.st_size if info else 0


def _readonly_connection(path: Path) -> sqlite3.Connection:
    _regular_nofollow(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    connection.execute("PRAGMA query_only = ON")
    return connection


def take_snapshot(codex_home: str | Path | None = None, *, include_counts: bool = False) -> IOSnapshot:
    home = resolve_codex_home(codex_home)
    _validate_codex_home(home, for_write=False, filesystem_detector=detect_mount)
    db = database_path(home)
    if not db.is_file():
        raise FileNotFoundError(db)
    max_id = row_count = trace_count = None
    trigger_installed = False
    query_error = None
    try:
        with closing(_readonly_connection(db)) as connection:
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
        captured_at=time.time(), database_bytes=_file_size(db),
        wal_bytes=_file_size(Path(f"{db}-wal")), shm_bytes=_file_size(Path(f"{db}-shm")),
        max_id=max_id, row_count=row_count, trace_count=trace_count,
        trigger_installed=trigger_installed, query_error=query_error,
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
    *, samples: int = 2, interval: float = 15.0,
    process_detector: ProcessDetector = find_codex_processes,
    sleeper: Callable[[float], None] = time.sleep,
    include_counts: bool = False,
    filesystem_detector: FilesystemDetector = detect_mount,
) -> IOAuditResult:
    if samples < 1 or samples > 10:
        raise ValueError("samples must be between 1 and 10")
    if interval < 0 or interval > 300:
        raise ValueError("interval must be between 0 and 300 seconds")
    home = resolve_codex_home(codex_home)
    mount = _validate_codex_home(home, for_write=False, filesystem_detector=filesystem_detector)
    captured = []
    for index in range(samples):
        captured.append(take_snapshot(home, include_counts=include_counts))
        if index + 1 < samples:
            sleeper(interval)
    first, last = captured[0], captured[-1]
    duration = max(0.0, last.captured_at - first.captured_at)
    wal_growth = last.wal_bytes - first.wal_bytes
    id_growth = last.max_id - first.max_id if first.max_id is not None and last.max_id is not None else None
    denominator = duration if duration > 0 else 1.0
    wal_rate = wal_growth / denominator
    id_rate = id_growth / denominator if id_growth is not None else None
    return IOAuditResult(
        codex_home=home, database=database_path(home), filesystem=mount.filesystem,
        processes=tuple(process_detector()), snapshots=tuple(captured),
        wal_growth_bytes=wal_growth, max_id_growth=id_growth, duration_seconds=duration,
        wal_bytes_per_second=wal_rate, ids_per_second=id_rate,
        risk=_risk_level(wal_rate, id_rate, (item.query_error for item in captured)),
    )


def _require_idle(process_detector: ProcessDetector) -> None:
    processes = process_detector()
    if processes:
        detail = "; ".join(f"pid={item.pid} {item.command}" for item in processes)
        raise CodexActiveError(
            "active Codex process detected; no database changes were made. "
            "Save work, close Codex Desktop/CLI/IDE integrations, then retry. " + detail
        )


@contextmanager
def _maintenance_lock(home: Path) -> Iterator[None]:
    lock = home / ".ai-rules-manager-maintenance.lock"
    try:
        info = lock.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise UnsafeCodexHomeError(f"unsafe maintenance lock path: {lock}")
    except FileNotFoundError:
        pass
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    try:
        os.chmod(lock, 0o600, follow_symlinks=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MaintenanceBusyError("another Codex maintenance operation is active") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _existing_backup_usage(root: Path) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    if root.is_symlink() or not root.is_dir():
        raise UnsafeCodexHomeError(f"unsafe backup root: {root}")
    count = total = 0
    for entry in root.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        count += 1
        for item in entry.iterdir():
            info = _regular_nofollow(item, required=False)
            if info:
                total += info.st_size
    return count, total


def _copy_reflink_or_stream(source: Path, destination: Path) -> None:
    before = _regular_nofollow(source)
    assert before is not None
    src_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    dst_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        cloned = False
        try:
            fcntl.ioctl(dst_fd, FICLONE, src_fd)
            cloned = True
        except OSError as exc:
            if exc.errno not in {errno.EOPNOTSUPP, errno.ENOTTY, errno.EXDEV, errno.EINVAL}:
                raise
        if not cloned:
            with os.fdopen(os.dup(src_fd), "rb") as src, os.fdopen(os.dup(dst_fd), "wb") as dst:
                shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
        else:
            os.fsync(dst_fd)
    finally:
        os.close(src_fd)
        os.close(dst_fd)
    after = _regular_nofollow(source)
    assert after is not None
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise RuntimeError(f"source changed during backup: {source}")
    os.chmod(destination, 0o600, follow_symlinks=False)


def _backup_database(
    db: Path, operation: str, *, backup_root: Path | None,
    max_backup_bytes: int, max_backup_total_bytes: int, max_backup_count: int,
) -> Path:
    sources = [Path(f"{db}{suffix}") for suffix in SIDECAR_SUFFIXES if Path(f"{db}{suffix}").exists()]
    total_source = sum(_file_size(path) for path in sources)
    if total_source > max_backup_bytes:
        raise RuntimeError(
            f"backup would copy {total_source} bytes, exceeding limit {max_backup_bytes}; "
            "use a larger explicit --max-backup-bytes or move backup to another local disk"
        )
    root = (backup_root or (db.parent / "backups")).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.resolve(strict=True) != root:
        raise UnsafeCodexHomeError(f"backup root must not contain symlink components: {root}")
    backup_mount = detect_mount(root)
    if backup_mount.filesystem.lower() in UNSAFE_FILESYSTEMS or backup_mount.filesystem.lower().startswith("fuse.sshfs"):
        raise UnsafeCodexHomeError(
            f"refusing backup on unsafe filesystem {backup_mount.filesystem!r} mounted at {backup_mount.mount_point}"
        )
    os.chmod(root, 0o700)
    count, existing_total = _existing_backup_usage(root)
    if count >= max_backup_count:
        raise RuntimeError(f"backup count limit reached ({count}/{max_backup_count}); archive or remove old backups manually")
    if existing_total + total_source > max_backup_total_bytes:
        raise RuntimeError("backup storage budget would be exceeded; archive or remove old backups manually")
    free = shutil.disk_usage(root).free
    if free < total_source + MIN_FREE_MARGIN_BYTES:
        raise RuntimeError(f"insufficient free space for safe backup: need {total_source + MIN_FREE_MARGIN_BYTES}, have {free}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = root / f"logs-2-{operation}-{stamp}"
    backup_dir.mkdir(mode=0o700)
    copied = []
    try:
        for source in sources:
            destination = backup_dir / source.name
            _copy_reflink_or_stream(source, destination)
            copied.append(source.name)
        metadata = {
            "schema": 2, "operation": operation,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_name": db.name, "files": copied, "source_bytes": total_source,
        }
        meta = backup_dir / "metadata.json"
        meta.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(meta, 0o600)
        return backup_dir
    except Exception:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise


def _validate_database(connection: sqlite3.Connection, *, full_integrity_check: bool) -> None:
    pragma = "integrity_check" if full_integrity_check else "quick_check"
    integrity = [row[0] for row in connection.execute(f"PRAGMA {pragma}")]
    if integrity != ["ok"]:
        raise RuntimeError(f"database {pragma} failed: " + "; ".join(integrity))
    table_exists = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs')"
    ).fetchone()[0]
    if table_exists != 1:
        raise RuntimeError("logs table not found; Codex database schema may have changed")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(logs)")}
    if "id" not in columns:
        raise RuntimeError("logs table is missing required id column")


def _checkpoint(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError("unexpected wal_checkpoint result")
    return int(row[0]), int(row[1]), int(row[2])


def _maintenance(
    codex_home: str | Path | None,
    *, install: bool, process_detector: ProcessDetector,
    filesystem_detector: FilesystemDetector, backup_root: Path | None,
    max_backup_bytes: int, max_backup_total_bytes: int, max_backup_count: int,
    full_integrity_check: bool,
) -> MaintenanceResult:
    home = resolve_codex_home(codex_home)
    _validate_codex_home(home, for_write=True, filesystem_detector=filesystem_detector)
    _require_idle(process_detector)
    db = database_path(home)
    _regular_nofollow(db)
    for suffix in ("-wal", "-shm"):
        _regular_nofollow(Path(f"{db}{suffix}"), required=False)
    with _maintenance_lock(home):
        _require_idle(process_detector)
        backup_dir = _backup_database(
            db, "guard" if install else "restore", backup_root=backup_root,
            max_backup_bytes=max_backup_bytes, max_backup_total_bytes=max_backup_total_bytes,
            max_backup_count=max_backup_count,
        )
        _require_idle(process_detector)
        stage = "backup_complete"
        try:
            with closing(sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=5.0)) as connection:
                connection.execute("PRAGMA busy_timeout = 5000")
                _validate_database(connection, full_integrity_check=full_integrity_check)
                if install:
                    connection.execute(
                        f'''CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAME}
                            BEFORE INSERT ON logs
                            BEGIN
                                SELECT RAISE(IGNORE);
                            END'''
                    )
                else:
                    connection.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME}")
                connection.commit()
                stage = "trigger_committed" if install else "trigger_removed"
                checkpoint = _checkpoint(connection)
                status = "completed" if checkpoint[0] == 0 else f"{stage}_checkpoint_busy"
        except Exception as exc:
            raise RuntimeError(
                f"maintenance failed at stage={stage}; untouched backup is available at {backup_dir}"
            ) from exc
        return MaintenanceResult(
            database=db, backup_dir=backup_dir, trigger_installed=install, status=status,
            checkpoint_busy=checkpoint[0], checkpoint_frames=checkpoint[1], checkpointed_frames=checkpoint[2],
        )


def apply_log_guard(
    codex_home: str | Path | None = None, *, process_detector: ProcessDetector = find_codex_processes,
    filesystem_detector: FilesystemDetector = detect_mount, backup_root: Path | None = None,
    max_backup_bytes: int = DEFAULT_MAX_BACKUP_BYTES,
    max_backup_total_bytes: int = DEFAULT_MAX_BACKUP_TOTAL_BYTES,
    max_backup_count: int = DEFAULT_MAX_BACKUP_COUNT,
    full_integrity_check: bool = False,
) -> MaintenanceResult:
    return _maintenance(
        codex_home, install=True, process_detector=process_detector,
        filesystem_detector=filesystem_detector, backup_root=backup_root,
        max_backup_bytes=max_backup_bytes, max_backup_total_bytes=max_backup_total_bytes,
        max_backup_count=max_backup_count, full_integrity_check=full_integrity_check,
    )


def restore_log_writes(
    codex_home: str | Path | None = None, *, process_detector: ProcessDetector = find_codex_processes,
    filesystem_detector: FilesystemDetector = detect_mount, backup_root: Path | None = None,
    max_backup_bytes: int = DEFAULT_MAX_BACKUP_BYTES,
    max_backup_total_bytes: int = DEFAULT_MAX_BACKUP_TOTAL_BYTES,
    max_backup_count: int = DEFAULT_MAX_BACKUP_COUNT,
    full_integrity_check: bool = False,
) -> MaintenanceResult:
    return _maintenance(
        codex_home, install=False, process_detector=process_detector,
        filesystem_detector=filesystem_detector, backup_root=backup_root,
        max_backup_bytes=max_backup_bytes, max_backup_total_bytes=max_backup_total_bytes,
        max_backup_count=max_backup_count, full_integrity_check=full_integrity_check,
    )
