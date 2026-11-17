"""Small shared primitives. No filesystem mutation at import time."""

from __future__ import annotations
import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Iterator
from .recovery import normalize_system_path

CHUNK = 1024 * 1024
APP_ID = 0x41503230


class Problem(Exception):
    def __init__(self, code: str, message: str, **detail: Any):
        super().__init__(message)
        self.code, self.detail = code, detail

    def record(self) -> dict:
        return {"code": self.code, "message": str(self), "detail": self.detail}


def require(condition: bool, code: str, message: str, **detail: Any) -> None:
    if not condition:
        raise Problem(code, message, **detail)


def now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def uid(prefix: str) -> str:
    return prefix + "-" + uuid.uuid4().hex[:16]


def json_read(path: Path, limit: int = 16 * 1024 * 1024) -> Any:
    require(
        path.is_file() and path.stat().st_size <= limit,
        "JSON_SIZE",
        "Missing or oversized JSON document",
        path=str(path),
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "JSON_DUPLICATE", "Duplicate JSON key", key=key)
            result[key] = value
        return result

    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(
            stream,
            object_pairs_hook=unique,
            parse_constant=lambda x: (_ for _ in ()).throw(
                Problem("JSON_NUMBER", "Non-finite JSON number")
            ),
        )


def fsync_dir(path: Path) -> None:
    # Windows has no equivalent to POSIX directory fsync in the standard library.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial-" + uuid.uuid4().hex[:8])
    try:
        with temp.open("xb") as out:
            out.write(canonical(value) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    except BaseException:
        # A partial is retained as failure evidence; no completed file is advertised.
        raise


def hash_file(path: Path, progress=None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            h.update(block)
            if progress:
                progress.advance(len(block), str(path))
    return h.hexdigest()


def bytes_value(value: str | int | float) -> int:
    if type(value) is int:
        require(0 <= value <= 2**63 - 1, "SIZE_RANGE", "Byte size is out of range")
        return value
    text = str(value).strip()
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?i?B)?", text, re.I)
    require(
        bool(m), "SIZE_FORMAT", "Use integer bytes or a unit such as 100GB or 100GiB", value=text
    )
    from decimal import Decimal

    unit = (m[2] or "B").upper()
    power = "BKMGTPE".index(unit[0]) if unit[0] != "B" else 0
    result = int(Decimal(m[1]) * ((1024 if "I" in unit else 1000) ** power))
    require(0 <= result <= 2**63 - 1, "SIZE_RANGE", "Byte size is out of range")
    return result


def sizes(n: int) -> str:
    def one(base, units):
        x = float(n)
        i = 0
        while abs(x) >= base and i < len(units) - 1:
            x /= base
            i += 1
        return f"{x:,.2f} {units[i]}" if i else f"{n:,} B"

    return (
        one(1000, ["B", "KB", "MB", "GB", "TB", "PB", "EB"])
        + " / "
        + one(1024, ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"])
    )


def rel_parts(value: str, root_ok: bool = False) -> list[str]:
    require(isinstance(value, str), "PATH_TYPE", "Path must be a string")
    if value == "" and root_ok:
        return []
    require(
        value and len(value.encode("utf-8", "strict")) <= 32768,
        "PATH_LENGTH",
        "Empty or excessively long member path",
    )
    parts = value.split("/")
    require(
        not value.startswith(("/", "\\"))
        and "\\" not in value
        and "\0" not in value
        and not re.match(r"^[A-Za-z]:", value),
        "UNSAFE_PATH",
        "Unsafe archive member path",
        path=value,
    )
    require(
        all(p not in ("", ".", "..") for p in parts),
        "UNSAFE_PATH",
        "Empty or traversing path component",
        path=value,
    )
    return parts


def portable_name(name: str) -> bool:
    stem = name.split(".")[0].upper()
    return not (
        re.search(r'[<>:"|?*\\\x00-\x1f]', name)
        or name.endswith((" ", "."))
        or stem
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    )


def collision_key(name: str) -> str:
    # Conservative interchange collision detector, NOT a filesystem identity rule.
    return unicodedata.normalize("NFC", name).casefold()


def is_link(st) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def no_links(path: Path, missing_ok: bool = False) -> Path:
    path = normalize_system_path(os.path.expanduser(str(path)))
    chain = [path, *path.parents]
    for p in reversed(chain):
        try:
            st = p.lstat()
        except FileNotFoundError:
            require(missing_ok, "MISSING_PATH", "Path does not exist", path=str(p))
            continue
        require(
            not is_link(st),
            "LINK_PATH",
            "Symbolic links and reparse points are not permitted here",
            path=str(p),
        )
    return path


def within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def disjoint(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return not within(a, b) and not within(b, a)


def root_identity(path: Path) -> dict:
    st = path.stat()
    return {"device": str(st.st_dev), "inode": str(st.st_ino), "platform": sys.platform}


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), "LOCK_LINK", "Lock path is a link")
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Problem(
                "BUSY", "Another operation owns this workspace or destination", path=str(path)
            ) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def regular_source(root: Path, relative: str):
    """No-follow descriptor traversal on POSIX; checked path traversal on Windows.

    Windows path validation is best effort against concurrent hostile replacement;
    this is not a sandbox for an attacker controlling the source directory.
    """
    parts = rel_parts(relative)
    root = no_links(root)
    descriptors = []
    try:
        if os.name != "nt" and os.open in os.supports_dir_fd:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(root, flags)
            descriptors.append(fd)
            for part in parts[:-1]:
                fd = os.open(part, flags, dir_fd=fd)
                descriptors.append(fd)
            final = os.open(
                parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                dir_fd=fd,
            )
        else:
            target = no_links(root.joinpath(*parts))
            final = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        with os.fdopen(final, "rb") as stream:
            st = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(st.st_mode) and not is_link(st),
                "NOT_REGULAR",
                "Source is not an ordinary regular file",
                path=relative,
            )
            yield stream, st
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
