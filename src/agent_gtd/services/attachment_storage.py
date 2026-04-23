"""On-disk storage helpers for file attachments."""

import contextlib
import os
import re
import shutil
from pathlib import Path

_DEFAULT_ROOT = str(Path.home() / ".agent-gtd-data" / "attachments")


def get_attachments_root() -> Path:
    """Return the root directory for attachment storage.

    Uses the ``AGENT_GTD_ATTACHMENTS_ROOT`` env var; falls back to
    ``~/.agent-gtd-data/attachments``.

    The directory is created lazily on first write (see :func:`ensure_item_dir`).
    Read and delete callers that find nothing on disk treat it as a no-op.
    """
    return Path(os.environ.get("AGENT_GTD_ATTACHMENTS_ROOT", _DEFAULT_ROOT))


def ensure_item_dir(item_id: str) -> Path:
    """Create and return the per-item attachment directory.

    Called by the upload endpoint (Part 2) immediately before writing a file.
    This is where the lazy ``mkdir(parents=True, exist_ok=True)`` happens.

    Args:
        item_id: Parent item UUID.

    Returns:
        The newly-created (or already-existing) directory path.
    """
    item_dir = get_attachments_root() / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    return item_dir


def build_storage_path(item_id: str, attachment_id: str, safe_filename: str) -> str:
    """Build a relative storage path for a new attachment.

    Args:
        item_id: The parent item's UUID.
        attachment_id: The new attachment's UUID.
        safe_filename: A sanitized filename (use :func:`sanitize_filename` first).

    Returns:
        Relative path of the form ``<item_id>/<attachment_id>-<safe_filename>``.
    """
    return f"{item_id}/{attachment_id}-{safe_filename}"


def absolute_path(storage_path: str) -> Path:
    """Return the absolute filesystem path for a stored attachment.

    Args:
        storage_path: Relative path as stored in the database.

    Returns:
        Absolute :class:`~pathlib.Path` under the attachments root.
    """
    return get_attachments_root() / storage_path


def sanitize_filename(raw: str) -> str:
    """Return a filesystem-safe version of *raw*.

    Rules:
    - Strip any character outside ``[A-Za-z0-9._-]`` (including path separators).
    - Preserve the file extension (everything after the last dot).
    - Truncate to 200 characters, preserving the extension.
    - Falls back to ``"file"`` (with extension if any) when the base is empty.

    Args:
        raw: The original, user-supplied filename.

    Returns:
        A sanitized filename safe for use as a path component.
    """
    _allowed = re.compile(r"[^A-Za-z0-9._\-]")

    if "." in raw:
        base, _, ext_raw = raw.rpartition(".")
        clean_ext = _allowed.sub("", ext_raw)
        ext = f".{clean_ext}" if clean_ext else ""
        clean_base = _allowed.sub("", base)
    else:
        ext = ""
        clean_base = _allowed.sub("", raw)

    # Fallback base name
    if not clean_base:
        clean_base = "file"

    result = clean_base + ext

    # Truncate total length to 200, preserving extension
    if len(result) > 200:
        max_base = 200 - len(ext)
        result = clean_base[:max_base] + ext

    return result


def delete_file(storage_path: str) -> None:
    """Delete a single attachment file from disk.

    Best-effort: silently ignores :exc:`FileNotFoundError`.

    Args:
        storage_path: Relative path as stored in the database.
    """
    with contextlib.suppress(FileNotFoundError):
        absolute_path(storage_path).unlink()


def delete_item_files(item_id: str) -> None:
    """Remove the per-item attachment directory and all files within it.

    Best-effort: silently ignores missing directories.  Called during item
    deletion so that orphaned files are cleaned up before the DB row (and its
    ``ON DELETE CASCADE`` children) disappear.

    Args:
        item_id: The item whose attachment directory should be removed.
    """
    item_dir = get_attachments_root() / item_id
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(item_dir)
