"""
Cross-run, cross-session cache for EasyPrivacy match verdicts.

``EasyPrivacyMatcher.match(url, doc_url, type)`` is a pure function of its
inputs for a fixed ruleset, and profiling on the 100k-site crawl showed ~96%
of analysis runtime going into it (specifically the ~3.5k-regex generic-rule
scan inside ``_find_matching_rule``). ``CookieDataset`` already memoises this
in-process via ``_ep_match_cache`` — but that memo dies with the process. Given
the crawl's ``{country}/{browser}/{site}`` layout (the *same* site gets
re-matched once per country x browser combination, almost always against the
same tracker request/document URLs) and the natural overlap of common trackers
across sites, persisting the memo means the expensive work is paid for *once*,
ever, per unique ``(url, doc_url, type)`` triple — not once per run.

Keyed on a fingerprint of the cached EasyPrivacy ruleset file(s) under
``tracker_cache_dir`` (stat-based, like :mod:`analysis.src.cache`'s
``dir_fingerprint``): if the list is refreshed, the fingerprint changes and the
stale memo is silently ignored rather than serving verdicts from an old
ruleset.
"""

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


def load(cache_dir: str, fingerprint: str) -> dict[MatchKey, bool] | None:
    """Return the persisted memo for ``fingerprint``, or ``None`` if absent/stale."""
    p = _path(cache_dir, fingerprint)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            data = pickle.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save(cache_dir: str, fingerprint: str, data: dict[MatchKey, bool]) -> None:
    """Persist ``data`` atomically (temp file + ``os.replace``)."""
    os.makedirs(cache_dir, exist_ok=True)
    p = _path(cache_dir, fingerprint)
    tmp = str(p) + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, p)
