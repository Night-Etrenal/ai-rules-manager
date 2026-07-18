from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path, PurePath


class UnsafePathError(ValueError):
    """Raised when a path escapes its trusted root or crosses a symlink."""


def _relative_parts(relative: str | Path) -> tuple[str, ...]:
    path = PurePath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafePathError(f"unsafe relative path: {relative}")
    return tuple(path.parts)


def _root(root: Path) -> Path:
    resolved = root.expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise UnsafePathError(f"trusted root is not a directory: {resolved}")
    return resolved


def _ensure_parent(root: Path, parts: tuple[str, ...], mode: int = 0o755) -> Path:
    current = root
    for part in parts:
        candidate = current / part
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            candidate.mkdir(mode=mode)
            info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise UnsafePathError(f"unsafe parent component: {candidate}")
        current = candidate
    return current


def safe_path(root: Path, relative: str | Path, *, allow_missing: bool = True) -> Path:
    trusted = _root(root)
    parts = _relative_parts(relative)
    current = trusted
    missing_parent = False
    for part in parts[:-1]:
        candidate = current / part
        if missing_parent:
            current = candidate
            continue
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if not allow_missing:
                raise
            missing_parent = True
            current = candidate
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise UnsafePathError(f"unsafe parent component: {candidate}")
        current = candidate
    target = current / parts[-1]
    try:
        info = target.lstat()
    except FileNotFoundError:
        if not allow_missing:
            raise
        return target
    if stat.S_ISLNK(info.st_mode):
        raise UnsafePathError(f"refusing symlink target: {target}")
    return target


def safe_regular_file(root: Path, relative: str | Path, *, required: bool = True) -> Path | None:
    try:
        target = safe_path(root, relative, allow_missing=not required)
    except FileNotFoundError:
        if required:
            raise
        return None
    if not target.exists():
        if required:
            raise FileNotFoundError(target)
        return None
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"expected regular file: {target}")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(_root(root))
    except ValueError as exc:
        raise UnsafePathError(f"file escapes trusted root: {target}") from exc
    return target


def safe_directory(root: Path, relative: str | Path, *, mode: int = 0o755) -> Path:
    trusted = _root(root)
    parts = _relative_parts(relative)
    return _ensure_parent(trusted, parts, mode=mode)


def atomic_write_bytes(
    root: Path,
    relative: str | Path,
    data: bytes,
    *,
    mode: int = 0o644,
    skip_if_unchanged: bool = True,
) -> bool:
    trusted = _root(root)
    parts = _relative_parts(relative)
    parent = _ensure_parent(trusted, parts[:-1]) if parts[:-1] else trusted
    target = parent / parts[-1]
    try:
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise UnsafePathError(f"refusing non-regular target: {target}")
        if skip_if_unchanged and target.read_bytes() == data:
            return False
    except FileNotFoundError:
        pass

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(parent, flags)
    temp_name = f".{parts[-1]}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(temp_name, file_flags, mode, dir_fd=parent_fd)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            existing = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise UnsafePathError(f"refusing non-regular target: {target}")
        except FileNotFoundError:
            pass
        os.replace(temp_name, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.chmod(parts[-1], mode, dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
        return True
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def atomic_write_text(
    root: Path,
    relative: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o644,
    skip_if_unchanged: bool = True,
) -> bool:
    return atomic_write_bytes(
        root,
        relative,
        text.encode(encoding),
        mode=mode,
        skip_if_unchanged=skip_if_unchanged,
    )


def safe_unlink(root: Path, relative: str | Path) -> bool:
    target = safe_path(root, relative, allow_missing=True)
    if not target.exists():
        return False
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"refusing to unlink non-regular file: {target}")
    target.unlink()
    return True
