"""
Cross-run cache for the *annotation* layer: the tiered tracker labels
(``tracker_tier`` / ``tracker_signals``) plus the three relational artifacts
they are derived from (``shared_groups``, ``sync_events``, ``cross_domain_reads``).

The enriched ``cookies``/``sites`` frames are already cached by
:mod:`analysis.src.cache`; this module sits one level up and persists what
``FrameAccess.classified_cookies`` adds on top — so a plot script that needs the
labels loads them from disk instead of recomputing three whole-dataset
relational passes plus a per-row classification.

Only the two *label columns* are stored (not a second copy of the multi-GB
cookies frame): the labels are re-joined to the already-cached ``cookies`` frame
at load time, by position, which is sound because the cache key embeds the
cookies fingerprint — a different cookies frame yields a different key and a
rebuild. The ``is_tracker`` boolean is **not** stored — it is re-derived from
``tracker_tier >= "probable"`` at load time in
:attr:`~analysis.CookieDataset.classified_cookies` so the definition lives in
one place. Layout per key:

    {key}.labels.parquet        # tracker_tier / tracker_signals
    {key}.shared.json           # shared_groups
    {key}.sync.json             # sync_events
    {key}.reads.json            # cross_domain_reads
    {key}.classified.meta.json  # bookkeeping
"""

from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path

import orjson

import pandas as pd

from .classifier import TIERS
from .progress import bar

# Bump when the label columns or classifier semantics change so old caches are
# ignored even if the underlying cookies frame is unchanged.
# v2: removed tracker_like; is_tracker is now derived from tracker_tier >= "probable"
#     at load time instead of being stored.
CLASSIFIED_SCHEMA_VERSION = 2

LABEL_COLUMNS = ["tracker_tier", "tracker_signals"]


def classified_fingerprint(base_key: str, extra_config_repr: str) -> str:
    """Stable hex digest for the annotation cache.

    ``base_key`` is the cookies-frame fingerprint (so any change to the input
    data or frame-affecting config already invalidates this), extended with the
    label-affecting config the cookies key omits (``sync_min_bits``, relational
    defaults) and a schema version.
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(
        f"c{CLASSIFIED_SCHEMA_VERSION}\0{base_key}\0{extra_config_repr}\0".encode()
    )
    return h.hexdigest()


def _paths(cache_dir: str, key: str) -> dict[str, Path]:
    base = Path(cache_dir)
    return {
        "labels": base / f"{key}.labels.parquet",
        "labels_pkl": base / f"{key}.labels.pkl",
        "shared": base / f"{key}.shared.json",
        "sync": base / f"{key}.sync.json",
        "reads": base / f"{key}.reads.json",
        "meta": base / f"{key}.classified.meta.json",
    }


def load(cache_dir: str, key: str) -> tuple[pd.DataFrame, dict] | None:
    """Return ``(labels_df, artifacts)`` for ``key`` or None if absent.

    ``artifacts`` is ``{"shared_groups", "sync_events", "cross_domain_reads"}``.
    ``labels_df`` carries the three label columns with a fresh ``RangeIndex``;
    the caller re-joins it to ``cookies`` by position.
    """
    p = _paths(cache_dir, key)
    if not p["meta"].exists():
        return None
    try:
        meta = orjson.loads(p["meta"].read_bytes())
        if meta.get("schema_version") != CLASSIFIED_SCHEMA_VERSION:
            return None
    except Exception:
        return None
    try:
        with bar("load classified cache", total=2, unit=" steps", leave=False) as b:
            if p["labels"].exists():
                labels = pd.read_parquet(p["labels"])
            elif p["labels_pkl"].exists():
                with open(p["labels_pkl"], "rb") as fh:
                    labels = pickle.load(fh)
            else:
                return None
            b.update()
            # Re-establish the ordered categorical (parquet/pickle round-trips may
            # drop the ordering flag).
            labels["tracker_tier"] = pd.Categorical(
                labels["tracker_tier"], categories=TIERS, ordered=True
            )
            artifacts = {
                "shared_groups": orjson.loads(p["shared"].read_bytes()),
                "sync_events": orjson.loads(p["sync"].read_bytes()),
                "cross_domain_reads": orjson.loads(p["reads"].read_bytes()),
            }
            b.update()
        return labels, artifacts
    except Exception:
        return None


def save(
    cache_dir: str,
    key: str,
    labels: pd.DataFrame,
    artifacts: dict,
    meta: dict,
) -> None:
    """Persist label columns + relational artifacts atomically.

    ``labels`` must contain :data:`LABEL_COLUMNS`; only those are written.
    ``artifacts`` must contain ``shared_groups`` / ``sync_events`` /
    ``cross_domain_reads`` (JSON-serialisable lists of dicts).
    """
    os.makedirs(cache_dir, exist_ok=True)
    p = _paths(cache_dir, key)

    out = labels[LABEL_COLUMNS].reset_index(drop=True).copy()
    # Store the tier as plain strings for a stable, engine-agnostic round-trip;
    # load() re-casts to the ordered categorical.
    out["tracker_tier"] = out["tracker_tier"].astype(str)

    used = "parquet"
    try:
        _atomic(p["labels"], lambda tmp: out.to_parquet(tmp, index=False))
    except Exception:
        used = "pickle"
        _atomic(p["labels_pkl"], lambda tmp: _pickle(out, tmp))

    _atomic(
        p["shared"],
        lambda tmp: Path(tmp).write_bytes(orjson.dumps(artifacts["shared_groups"])),
    )
    _atomic(
        p["sync"],
        lambda tmp: Path(tmp).write_bytes(orjson.dumps(artifacts["sync_events"])),
    )
    _atomic(
        p["reads"],
        lambda tmp: Path(tmp).write_bytes(
            orjson.dumps(artifacts["cross_domain_reads"])
        ),
    )
    meta = {
        **meta,
        "format": used,
        "schema_version": CLASSIFIED_SCHEMA_VERSION,
        "n_labels": int(len(out)),
    }
    _atomic(
        p["meta"],
        lambda tmp: Path(tmp).write_bytes(
            orjson.dumps(meta, option=orjson.OPT_INDENT_2)
        ),
    )


def _atomic(dest: Path, write) -> None:
    tmp = str(dest) + ".tmp"
    write(tmp)
    os.replace(tmp, dest)


def _pickle(obj, path) -> None:
    with open(path, "wb") as fh:
        pickle.dump(obj, fh)
