"""Standard-library distribution helpers shared by the qualification scripts."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil


def relative_name(name):
    """Accept one portable relative member name; never a drive or traversal."""
    value = name[:-1] if name.endswith("/") else name
    parts = value.split("/")
    if not value or "\\" in value or any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError("Unsafe archive member: " + repr(name))
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("Absolute archive member")
    return path


def extract_plain_tar(archive, destination):
    """Extract only validated plain files/directories, including on Python 3.8.

    The caller supplies an owned, empty directory. No link, special object,
    duplicate, absolute path or pre-existing output can be followed/replaced.
    This avoids disabling newer tarfile extraction protections on old Python.
    """
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or any(root.iterdir()):
        raise ValueError("Extraction requires an empty owned directory")
    entries = []
    names = set()
    total = 0
    for member in archive:
        relative = relative_name(member.name)
        if relative in names or not (member.isfile() or member.isdir()):
            raise ValueError("Duplicate or unsupported TAR member")
        names.add(relative)
        total += member.size
        if len(names) > 10000 or total > 1024 * 1024 * 1024 or member.size < 0:
            raise ValueError("Distribution exceeds qualification extraction limits")
        entries.append((member, relative))
    for member, relative in entries:
        target = root.joinpath(*relative.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("Missing plain-file content")
        with stream, target.open("xb") as output:
            shutil.copyfileobj(stream, output, 1024 * 1024)
        if target.stat().st_size != member.size:
            raise ValueError("Truncated TAR member")
        target.chmod(member.mode & 0o755)
