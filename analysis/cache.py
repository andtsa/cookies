"""
analysis/cache.py
-----------------
Cross-run cache for the enriched ``cookies`` / ``sites`` frames.

The cache is reused only while the data is unchanged: the key is a blake2b of
every site file's ``(relpath, size, mtime_ns)`` (stat-only — no file reads)
combined with the config that affects derived values and a schema version. Any
add/remove/edit changes the fingerprint and forces a rebuild.

Parquet (pyarrow) is preferred; if unavailable we fall back to pickle so the
cache still works without the optional dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path

import pandas as pd

# Bump when the enriched column schema changes so old caches are ignored.
SCHEMA_VERSION = 1


def dir_fingerprint(paths: list[Path], config_repr: str) -> str:
    """Stable hex digest of the dataset state + config."""
    h = hashlib.blake2b(digest_size=16)
    h.update(f"v{SCHEMA_VERSION}\0{config_repr}\0".encode())
    for p in sorted(paths):
        try:
            st = p.stat()
            h.update(f"{p}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{p}\0MISSING\n".encode())
    return h.hexdigest()


def _paths(cache_dir: str, key: str) -> dict[str, Path]:
    base = Path(cache_dir)
    return {
        "cookies": base / f"{key}.cookies.parquet",
        "sites": base / f"{key}.sites.parquet",
        "cookies_pkl": base / f"{key}.cookies.pkl",
        "sites_pkl": base / f"{key}.sites.pkl",
        "meta": base / f"{key}.meta.json",
    }


def load(cache_dir: str, key: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Return cached ``(cookies, sites)`` for ``key`` or None if absent."""
    p = _paths(cache_dir, key)
    if not p["meta"].exists():
        return None
    try:
        if p["cookies"].exists() and p["sites"].exists():
            return pd.read_parquet(p["cookies"]), pd.read_parquet(p["sites"])
        if p["cookies_pkl"].exists() and p["sites_pkl"].exists():
            with open(p["cookies_pkl"], "rb") as fh:
                cookies = pickle.load(fh)
            with open(p["sites_pkl"], "rb") as fh:
                sites = pickle.load(fh)
            return cookies, sites
    except Exception:
        return None
    return None


def save(
    cache_dir: str,
    key: str,
    cookies: pd.DataFrame,
    sites: pd.DataFrame,
    meta: dict,
) -> None:
    """Persist frames + meta atomically; degrade to pickle if parquet fails."""
    os.makedirs(cache_dir, exist_ok=True)
    p = _paths(cache_dir, key)
    used = "parquet"
    try:
        _atomic(p["cookies"], lambda tmp: cookies.to_parquet(tmp, index=False))
        _atomic(p["sites"], lambda tmp: sites.to_parquet(tmp, index=False))
    except Exception:
        used = "pickle"
        _atomic(p["cookies_pkl"], lambda tmp: _pickle(cookies, tmp))
        _atomic(p["sites_pkl"], lambda tmp: _pickle(sites, tmp))
    meta = {**meta, "format": used, "schema_version": SCHEMA_VERSION}
    _atomic(p["meta"], lambda tmp: Path(tmp).write_text(json.dumps(meta, indent=2)))


def _atomic(dest: Path, write) -> None:
    tmp = str(dest) + ".tmp"
    write(tmp)
    os.replace(tmp, dest)


def _pickle(obj, path) -> None:
    with open(path, "wb") as fh:
        pickle.dump(obj, fh)
