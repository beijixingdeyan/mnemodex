"""Configuration handling for mnemodex.

Store layout (inside a repository, by default):

    .mnemodex/
      config.json        repo-local configuration (git-ignored at init)
      memory.jsonl       append-only memory log (compacted on `gc`)
      index.json         the serialized knowledge graph + symbol index
      web/               generated web UI assets (optional)

User-level override: ``$MNEMODEX_HOME`` (default ``~/.mnemodex``) may hold a
``config.json`` with defaults merged below the repo-local config.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .errors import ConfigError
from . import util

DEFAULT_STORE_DIR = ".mnemodex"
CONFIG_FILE = "config.json"

_DEFAULTS: Dict[str, Any] = {
    "store_dir": DEFAULT_STORE_DIR,
    "index_depth": 12,  # maximum directory depth scanned
    "max_file_bytes": 1_000_000,  # files larger than this are skipped by the indexer
    "memory_hard_cap": 50_000,  # cap on memory entries before `gc` is forced
    "compression_budget_tokens": 8000,  # default context budget for `ask`/MCP
    "web_host": "127.0.0.1",  # the web UI only ever binds loopback by default
    "web_port": 8765,
    "languages": "auto",  # "auto" = every built-in language
    "respect_gitignore": True,
    "include_hidden": False,
    "ignore_patterns": [],  # extra repo-relative globs always ignored
    "autocategorize": True,  # guess memory kind from the text when not given
    "ttl_days": {"task": 30, "tip": 365, "gotcha": 730, "decision": 730, "api": 730, "convention": 730},
    "shared": True,  # allow git-tracking of the memory log (export) 
}

_KNOWN_KEYS = set(_DEFAULTS.keys())


def default_config() -> Dict[str, Any]:
    return dict(_DEFAULTS)


def _merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def user_config_path() -> str:
    home = os.environ.get("MNEMODEX_HOME") or os.path.join(
        os.path.expanduser("~"), ".mnemodex"
    )
    return os.path.join(home, CONFIG_FILE)


def load_user_config() -> Dict[str, Any]:
    path = user_config_path()
    if not os.path.exists(path):
        return {}
    try:
        data = util.read_json(path)
    except Exception as exc:  # pragma: no cover - defensive
        raise ConfigError(f"cannot read user config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"user config {path} must be a JSON object")
    return data


def discover_store(cwd: str) -> Optional[str]:
    """Walk up from *cwd* looking for a `.mnemodex` store directory.

    This is what makes mnemodex work from any subdirectory of a repo.
    """
    current = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(current, DEFAULT_STORE_DIR)
        if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, CONFIG_FILE)):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def repo_root_for_store(store_dir: str) -> str:
    """The repository root that owns a store directory."""
    return os.path.dirname(os.path.abspath(store_dir))


def write_config(store_dir: str, config: Dict[str, Any]) -> str:
    path = os.path.join(store_dir, CONFIG_FILE)
    util.atomic_write_json(path, config)
    return path


def load_config(store_dir: str) -> Dict[str, Any]:
    path = os.path.join(store_dir, CONFIG_FILE)
    if not os.path.exists(path):
        raise ConfigError(f"store {store_dir} has no {CONFIG_FILE}")
    data = util.read_json(path)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a JSON object")
    merged = _merge(default_config(), data)
    # Merge user-level config last? No — repo-local overrides user-level.
    merged = _merge(merged, load_user_config())
    validate(merged)
    return merged


def validate(config: Dict[str, Any]) -> None:
    for key in config:
        if key not in _KNOWN_KEYS:
            raise ConfigError(f"unknown configuration key: {key!r}")
    if not isinstance(config.get("ignore_patterns"), list):
        raise ConfigError("ignore_patterns must be a list of glob strings")
    if not isinstance(config.get("ttl_days"), dict):
        raise ConfigError("ttl_days must be an object")
    checks = {
        "index_depth": lambda v: isinstance(v, int) and 1 <= v <= 64,
        "max_file_bytes": lambda v: isinstance(v, int) and v > 0,
        "memory_hard_cap": lambda v: isinstance(v, int) and v > 0,
        "compression_budget_tokens": lambda v: isinstance(v, int) and v > 0,
        "web_port": lambda v: isinstance(v, int) and 0 <= v <= 65535,
    }
    for key, test in checks.items():
        if key in config and not test(config[key]):
            raise ConfigError(f"invalid value for {key!r}: {config[key]!r}")


def store_paths(store_dir: str) -> Dict[str, str]:
    """All well-known paths inside a store directory."""
    return {
        "store_dir": store_dir,
        "config": os.path.join(store_dir, CONFIG_FILE),
        "memory": os.path.join(store_dir, "memory.jsonl"),
        "index": os.path.join(store_dir, "index.json"),
        "web": os.path.join(store_dir, "web"),
        "log": os.path.join(store_dir, "mnemodex.log"),
        "lock": os.path.join(store_dir, ".lock"),
    }


def gitignore_append(repo_root: str, line: str) -> bool:
    """Append *line* to the repo's .gitignore if not already present.

    Returns True when the file was modified. Used by `mnemodex init` to keep
    the store out of the repository while still letting users opt in to
    tracking the exported memory files.
    """
    path = os.path.join(repo_root, ".gitignore")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        content = ""
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if line in lines:
        return False
    write_lines = lines + ["", f"# mnemodex runtime data (regenerate with `mnemodex init`)", line, ""]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(write_lines))
    return True