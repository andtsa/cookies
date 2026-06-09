from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path

MatchKey = tuple[str, str, str]


def ruleset_fingerprint(tracker_cache_dir: str) -> str:
    """Stable hex digest of the cached EasyPrivacy filter-list file(s)."""
    h = hashlib.blake2b(digest_size=16)
    base = Path(tracker_cache_dir)
    if base.is_dir():
        for p in sorted(base.glob("*.txt")):
            if "asyprivacy" not in p.name.lower():  # matches Easy/easy-privacy
                continue
            try:
                st = p.stat()
                h.update(f"{p.name}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
            except OSError:
                h.update(f"{p.name}\0MISSING\n".encode())
    return h.hexdigest()


def _path(cache_dir: str, fingerprint: str) -> Path:
    return Path(cache_dir) / f"ep_match_cache.{fingerprint}.pkl"


def _log_path(cache_dir: str, fingerprint: str) -> Path:
    return Path(cache_dir) / f"ep_match_cache.{fingerprint}.log"


def load(cache_dir: str, fingerprint: str) -> dict[MatchKey, bool] | None:
    """Return the persisted memo for ``fingerprint``, or ``None`` if absent/stale.

    Reads the consolidated ``.pkl`` snapshot and then replays any append-log
    written since the last consolidation (see :func:`append`). The log holds a
    sequence of pickled dict batches; later batches win on key collision.
    """
    p = _path(cache_dir, fingerprint)
    log = _log_path(cache_dir, fingerprint)
    if not p.exists() and not log.exists():
        return None
    data: dict[MatchKey, bool] = {}
    try:
        if p.exists():
            with open(p, "rb") as fh:
                base = pickle.load(fh)
            if isinstance(base, dict):
                data.update(base)
    except Exception:
        data = {}
    try:
        if log.exists():
            with open(log, "rb") as fh:
                while True:
                    try:
                        batch = pickle.load(fh)
                    except EOFError:
                        break
                    if isinstance(batch, dict):
                        data.update(batch)
    except Exception:
        pass  # a truncated log just means we replay what we can
    return data or None


def append(cache_dir: str, fingerprint: str, new_items: dict[MatchKey, bool]) -> None:
    """Append only the *new* verdicts to the log — O(len(new_items)), not O(total).

    This is the hot-path persistence during a long prefetch: each call writes a
    single pickled batch of just-computed verdicts, so checkpoint cost stays flat
    as the in-memory memo grows (instead of rewriting the whole dict each time).
    Consolidate with :func:`save` at the end to fold the log back into the
    snapshot.
    """
    if not new_items:
        return
    os.makedirs(cache_dir, exist_ok=True)
    with open(_log_path(cache_dir, fingerprint), "ab") as fh:
        pickle.dump(dict(new_items), fh, protocol=pickle.HIGHEST_PROTOCOL)


def save(cache_dir: str, fingerprint: str, data: dict[MatchKey, bool]) -> None:
    """Consolidate: write the full memo atomically and drop the append-log.

    One O(N) write — call this once at the end of a run (or from the
    non-parallel path), not on every checkpoint.
    """
    os.makedirs(cache_dir, exist_ok=True)
    p = _path(cache_dir, fingerprint)
    tmp = str(p) + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, p)
    # Snapshot now supersedes the log; remove it so future loads don't double-read.
    try:
        _log_path(cache_dir, fingerprint).unlink(missing_ok=True)
    except Exception:
        pass
