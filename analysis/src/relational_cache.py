"""
Cross-run cache for the *sync-subtype* and *third-party-read* relational tables.

These are derived purely from the raw crawl (request type / EasyPrivacy verdict /
JS stacks) plus the dataset's ``sync_min_bits``, so they are keyed by the same
fingerprint as the annotation cache (:mod:`analysis.src.classified_cache`) —
any change to the input data or the sync threshold yields a new key and a
rebuild. Unlike the annotation cache, they are stored independently so a sync
plot can load them from disk without triggering the full tier classification.

Layout per key::

    {key}.subtypes.v{V}.json   # sync_subtype_rows (deep=False)
    {key}.tpreads.v{V}.json     # third_party_reads
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Bump when the row shape produced by sync_subtype_rows / third_party_reads
# changes, so stale caches from an older layout are ignored.
RELATIONAL_SCHEMA_VERSION = 1


def _path(cache_dir: str, key: str, name: str) -> Path:
    return Path(cache_dir) / f"{key}.{name}.v{RELATIONAL_SCHEMA_VERSION}.json"


def load(cache_dir: str | None, key: str | None, name: str) -> list | None:
    """Return the cached list for ``name`` (e.g. "subtypes"), or None."""
    if not cache_dir or key is None:
        return None
    p = _path(cache_dir, key, name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save(cache_dir: str | None, key: str | None, name: str, data: list) -> None:
    """Persist ``data`` for ``name`` atomically (best-effort; never raises)."""
    if not cache_dir or key is None:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        dest = _path(cache_dir, key, name)
        tmp = str(dest) + ".tmp"
        Path(tmp).write_text(json.dumps(data))
        os.replace(tmp, dest)
    except Exception:
        pass
