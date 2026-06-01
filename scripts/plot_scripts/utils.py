"""
Shared color palette, data loaders, and save helper for all plot scripts.
"""

import json
import os
import glob
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

BG = "#fef2e6"
COLORS = [
    "#ba4f19",
    "#ecb157",
    "#a8879d",
    "#ae8775",
    "#5e311d",
    "#ffca7b",
    "#fcc0a6",
    "#6c4633",
    "#d8c9c0",
    "#dfcdbb",
]
ACCENT = "#ba4f19"  # primary highlight
ACCENT2 = "#ecb157"  # secondary highlight
DARK = "#5e311d"
MID = "#ae8775"
LIGHT = "#d8c9c0"


def apply_theme():
    mpl.rcParams.update(
        {
            "figure.facecolor": BG,
            "axes.facecolor": BG,
            "axes.edgecolor": DARK,
            "axes.labelcolor": DARK,
            "axes.titlecolor": DARK,
            "xtick.color": DARK,
            "ytick.color": DARK,
            "text.color": DARK,
            "grid.color": LIGHT,
            "grid.linewidth": 0.6,
            "font.family": "sans-serif",
            "font.size": 12,
            "axes.titlesize": 16,
            "axes.titleweight": "bold",
            "axes.labelsize": 13,
            "figure.dpi": 150,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "savefig.facecolor": BG,
            "legend.framealpha": 0.85,
            "legend.edgecolor": LIGHT,
        }
    )


def _iter_cookie_files(data_dir: str):
    """Yield (domain, browser, data) for every JSON file in data_dir.

    Searches recursively so both the old flat layout (data_dir/*.json) and the
    new browser-subdirectory layout (data_dir/{browser}/*.json) are covered.
    The ``browser`` value is the intermediate directory name (e.g. "chromium",
    "webkit"); it is "unknown" for files sitting directly in data_dir.
    """
    paths = sorted(glob.glob(os.path.join(data_dir, "**", "*.json"), recursive=True))
    if not paths:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        rel = os.path.relpath(path, data_dir)
        parts = rel.split(os.sep)
        browser = parts[0] if len(parts) > 1 else "unknown"
        domain = os.path.basename(path).replace(".json", "")
        yield domain, browser, data


def load_cookie_data(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        sites_df  – one row per site  (site_metadata fields + domain + browser)
        cookies_df – one row per cookie (all cookie fields + domain + browser +
                     set_by_third_party, set_by_type, set_by_ep_matched)
    """
    site_rows = []
    cookie_rows = []

    for domain, browser, data in _iter_cookie_files(data_dir):
        meta = data.get("site_metadata", {})

        site_rows.append(
            {
                "domain": domain,
                "browser": browser,
                "target_url": data.get("target_url", ""),
                "total_cookies": meta.get("total_cookies", 0),
                "num_session": meta.get("num_session", 0),
                "num_persistent": meta.get("num_persistent", 0),
                "avg_lifetime_days": meta.get("avg_lifetime_days", 0),
                "min_lifetime_days": meta.get("min_lifetime_days", 0),
                "max_lifetime_days": meta.get("max_lifetime_days", 0),
                "num_easyprivacy_requests": meta.get("num_easyprivacy_requests", 0),
                "pct_easyprivacy_requests": meta.get("pct_easyprivacy_requests", 0.0),
            }
        )

        for cookie in data.get("cookies", []):
            set_by = cookie.get("set_by") or {}
            ep = set_by.get("easyprivacy") or {}
            cookie_rows.append(
                {
                    "domain": domain,
                    "browser": browser,
                    "name": cookie.get("name"),
                    "session": cookie.get("session", True),
                    "cookie_type": cookie.get("cookie_type", "session"),
                    "secure": cookie.get("secure", False),
                    "httpOnly": cookie.get("httpOnly", False),
                    "sameSite": cookie.get("sameSite"),
                    "lifetime_days": cookie.get("lifetime_days", 0),
                    "set_by_url": set_by.get("url"),
                    "set_by_type": set_by.get("type"),
                    "set_by_initiator": set_by.get("initiator"),
                    "set_by_third_party": set_by.get("third_party"),
                    "set_by_ep_matched": ep.get("matched", False),
                }
            )

    sites_df = pd.DataFrame(site_rows)
    cookies_df = pd.DataFrame(cookie_rows)
    return sites_df, cookies_df


def load_tracker_cookies(data_dir: str) -> pd.DataFrame:
    """
    Load cookies that have is_tracker annotations.
    Skips files where is_tracker is absent (collected without --tracker-lists).

    Handles both the old schema (``False`` for non-trackers) and the new schema
    (``null`` / ``None`` for non-trackers).  In both cases the resulting
    ``is_tracker`` column is a plain bool.
    """
    rows = []
    skipped = 0

    for domain, browser, data in _iter_cookie_files(data_dir):
        for cookie in data.get("cookies", []):
            if "is_tracker" not in cookie:
                skipped += 1
                continue
            tracker_val = cookie["is_tracker"]
            # new schema: None means not a tracker; old schema: False means same
            if tracker_val is None or tracker_val is False:
                is_tracker = False
            else:
                is_tracker = bool(tracker_val.get("lists"))
            set_by = cookie.get("set_by") or {}
            rows.append(
                {
                    "domain": domain,
                    "browser": browser,
                    "name": cookie.get("name"),
                    "is_tracker": is_tracker,
                    "cookie_type": cookie.get("cookie_type", "session"),
                    "session": cookie.get("session", True),
                    "lifetime_days": cookie.get("lifetime_days") or 0,
                    "set_by_third_party": set_by.get("third_party"),
                }
            )

    if skipped:
        print(f"[warn] Skipped {skipped:,} cookies with no is_tracker field.")
    if not rows:
        raise ValueError(
            "No cookies with is_tracker found. "
            "Re-collect with --tracker-lists to annotate trackers."
        )
    return pd.DataFrame(rows)


def save_figure(out_dir: str, *filenames: str, facecolor: str = BG) -> None:
    """Save the current figure to one or more files, then close it."""
    os.makedirs(out_dir, exist_ok=True)
    for filename in filenames:
        out_path = os.path.join(out_dir, filename)
        plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=facecolor)
        # Plain ASCII arrow: a Windows cp1252 console cannot encode "→".
        print(f"Saved -> {out_path}")
    plt.close()


BUCKETS = [
    "Session",
    "< 1 day",
    "1–7 days",
    "8–30 days",
    "1–3 months",
    "3–12 months",
    "> 1 year",
]
BUCKET_COLORS = [
    "#a8879d",
    "#d8c9c0",
    "#ffca7b",
    "#fcc0a6",
    "#ecb157",
    "#ae8775",
    "#ba4f19",
]


def lifetime_bucket(days: float, is_session: bool) -> str:
    if is_session:
        return "Session"
    if days < 1:
        return "< 1 day"
    if days <= 7:
        return "1–7 days"
    if days <= 30:
        return "8–30 days"
    if days <= 90:
        return "1–3 months"
    if days <= 365:
        return "3–12 months"
    return "> 1 year"
