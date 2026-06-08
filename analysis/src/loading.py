from __future__ import annotations

import csv
import glob
import os
from pathlib import Path

import orjson

from .helpers import registered_domain
from .records import SiteRaw


def site_paths(data_dir: str | os.PathLike) -> list[Path]:
    """All site JSON files under ``data_dir`` (recursive, sorted)."""
    pattern = os.path.join(str(data_dir), "**", "*.json")
    return [Path(p) for p in sorted(glob.glob(pattern, recursive=True))]


def path_context(path: Path, data_dir: str | os.PathLike) -> tuple[str, str, str]:
    """Decode ``(country, browser, domain_slug)`` from a site path.

    Expects the canonical layout ``{country}/{browser}/{hexprefix}/{slug}.json``.
    Returns ``"unknown"`` for country/browser when the path is shorter.
    """
    parts = Path(path).relative_to(Path(data_dir)).parts
    slug = Path(path).stem
    country = parts[0] if len(parts) >= 4 else "unknown"
    browser = parts[1] if len(parts) >= 4 else "unknown"
    return country, browser, slug


def load_site(path: Path, data_dir: str | os.PathLike) -> SiteRaw | None:
    """Read one site JSON into a :class:`SiteRaw` (None on parse failure)."""
    try:
        with open(path, "rb") as fh:
            data = orjson.loads(fh.read())
    except (orjson.JSONDecodeError, OSError):
        return None
    country, browser, slug = path_context(path, data_dir)
    return SiteRaw(path=path, country=country, browser=browser, domain=slug, data=data)


def load_site_lists(site_lists: dict[str, str]) -> dict[str, tuple[str, int]]:
    """Build ``registered_domain -> (category, rank)`` from website-list CSVs.

    ``site_lists`` maps a category label to a ``rank,url`` CSV path. When a
    domain appears in several lists the *first* configured list wins (so callers
    put the more specific list, e.g. ``medical``, first). Missing files are
    skipped silently.
    """
    mapping: dict[str, tuple[str, int]] = {}
    for category, csv_path in (site_lists or {}).items():
        if not csv_path or not os.path.exists(csv_path):
            continue
        with open(csv_path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                dom = registered_domain(url)
                if not dom or dom in mapping:
                    continue
                try:
                    rank = int(row.get("rank") or 0)
                except ValueError:
                    rank = 0
                mapping[dom] = (category, rank)
    return mapping
