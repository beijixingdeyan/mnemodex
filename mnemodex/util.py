"""Utility helpers shared across mnemodex modules.

Privacy contract
----------------
Mnemodex is local-first and GitHub-upload friendly. Nothing we persist may
contain an absolute filesystem path, a machine name, or a user home path.
Every stored path is repo-relative; the only absolute path kept on disk is
the store root inside `.mnemodex/config.json`, which is git-ignored by
`mnemodex init`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

JsonValue = Union[None, bool, int, float, str, List["JsonValue"], Dict[str, "JsonValue"]]

# Tokens of 2..40 word characters; everything else is a delimiter.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,40}")
# Snake case, camel case and kebab case segmentor used to normalise
# identifiers like `buildCacheEviction` -> build + cache + eviction.
_WORD_BOUNDARY_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])|[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in is it its of on or that the
    this to was were will with not no but do does did done if then else when
    while return none true false self cls init new null undefined let const var
    def class import from export function async await using include pragma
    sizeof typeof int float double bool char string void public private
    protected static final override virtual
    """.split()
)


def split_words(text: str) -> Tuple[str, ...]:
    """Split text into lowercase word tokens suitable for weighting."""
    out: List[str] = []
    for raw in _TOKEN_RE.findall(text):
        for piece in _WORD_BOUNDARY_RE.findall(raw):
            low = piece.lower()
            if low not in _STOPWORDS:
                out.append(low)
    return tuple(out)


def ngrams(words: Sequence[str], n: int = 2) -> Tuple[str, ...]:
    """Character trigrams of joined words, used for lightweight fuzzy match."""
    if not words:
        return ()
    joined = "".join(words)
    if len(joined) < n:
        return (joined + " " * (n - len(joined)),)
    return tuple(joined[i : i + n] for i in range(len(joined) - n + 1))


def token_fingerprint(text: str) -> str:
    """Deterministic signature of a text's word bag (dedupe / similarity)."""
    words = sorted(split_words(text))
    if not words:
        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]
    return hashlib.sha1("\u0001".join(words).encode("utf-8")).hexdigest()[:16]


def short_hash(text: str, length: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:length]


def repo_relative(path: str, root: str) -> str:
    """Return *path* relative to *root*, using forward slashes.

    Public interface for the privacy contract: never call this and then store
    the returned value with a leading ``..`` — callers must have resolved the
    path inside the repo first.
    """
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def safe_join(root: str, rel: str) -> str:
    """Join *root* and a repo-relative path, refusing path traversal."""
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/") or rel == "..":
        raise ValueError(f"unsafe relative path: {rel!r}")
    return os.path.normpath(os.path.join(root, rel))


def is_binary(path: str, sample_size: int = 4096) -> bool:
    """Heuristic binary detection: NUL bytes or a high ratio of control bytes."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(sample_size)
    except OSError:
        return True
    if not head:
        return False
    if b"\x00" in head:
        return True
    control = sum(1 for b in head if b < 32 and b not in (9, 10, 13))
    return control / len(head) > 0.30


def detect_encoding(raw: bytes) -> str:
    """Best-effort encoding detection; defaults to UTF-8 per modern reality."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def read_text_file(path: str) -> str:
    """Read a text file with encoding auto-detection. Raises OSError on I/O."""
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw.decode(detect_encoding(raw), errors="replace")


def atomic_write_json(path: str, data: JsonValue) -> None:
    """Write JSON atomically (tmp file + rename) so crashes never corrupt it."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path) or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str) -> None:
    """Write plain text atomically."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str) -> JsonValue:
    """Read a JSON file (raises StoreCorruptError on bad content)."""
    from .errors import StoreCorruptError

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise StoreCorruptError(f"cannot parse {path}: {exc}") from exc


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def human_count(n: int) -> str:
    return f"{n:,}"


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token per 4 chars, +1 per whitespace word."""
    chars = len(text)
    words = len(re.findall(r"\S+", text))
    return max(1, int(chars / 4) + words // 3)


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - len(ellipsis))] + ellipsis


def first_line(text: str) -> str:
    line = (text or "").splitlines()[0] if text.splitlines() else ""
    return line.strip()


@contextmanager
def file_lock(path: str, timeout: float = 5.0) -> Iterator[None]:
    """A tiny, cross-platform advisory lock implemented with O_EXCL.

    Works on every OS and needs no fcntl. Stale locks (older than 5 minutes)
    are broken automatically so a killed process cannot wedge the store.
    """
    from .errors import StoreLockedError

    import time

    lock_path = path + ".lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()}\n{time.time():.6f}\n")
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
            except OSError:
                continue
            if age > 300:  # 5 minutes
                try:
                    os.unlink(lock_path)
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise StoreLockedError(lock_path)
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def copy_with_permissions(src: str, dst: str) -> None:
    """Copy a file preserving executable bits (POSIX installs)."""
    shutil.copy2(src, dst)
    mode = os.stat(src).st_mode
    if os.name == "posix":
        try:
            os.chmod(dst, mode)
        except OSError:
            pass


def stable_key(*parts: Any) -> str:
    """A deterministic key string for graph nodes / dedupe."""
    return "::".join(str(p) for p in parts)


def safe_name(name: str) -> str:
    """Sanitize a name for use in graph ids / dot output."""
    return re.sub(r"[^A-Za-z0-9_.:/-]", "_", name)


def sorted_natural(items: Sequence[str]) -> List[str]:
    """Sort with numeric-aware ordering: file2 < file10."""
    return sorted(items, key=lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)])


def utc_now() -> int:
    """Integer unix timestamp (seconds) — the store's time base."""
    import time

    return int(time.time())


def iso_now() -> str:
    """ISO-8601 UTC timestamp for human-facing output."""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def time_ago(ts: int, now: Optional[int] = None) -> str:
    """Human relative time like '3h ago'."""
    import time

    now = now or int(time.time())
    delta = max(0, now - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 86400 * 30:
        return f"{delta // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def walk_files(root: str) -> Iterator[str]:
    """Yield all regular files under *root*, depth-first, sorted per dir."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.isfile(path):
                yield path


def format_json(data: JsonValue) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def parse_int_or(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default