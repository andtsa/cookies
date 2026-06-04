"""
Shared color palette, data loaders, and save helper for all plot scripts.

The data loaders are now thin wrappers over ``analysis.CookieDataset`` (the
centralised analysis class). They preserve the historical column names plot
scripts expect — including legacy aliases — so existing plots keep working while
reading from the single, correctly-enriched source of truth.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.colors as mc
import matplotlib.pyplot as plt

# Make the repo-root ``analysis`` package importable from scripts/plot_scripts/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from analysis import CookieDataset  # noqa: E402
from analysis.enrich import BUCKETS, BUCKET_COLORS, lifetime_bucket  # noqa: E402,F401

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
    """Yield ``(domain, browser, data)`` for every site JSON under ``data_dir``.

    Backward-compatibility shim for plot scripts that consume raw site dicts
    directly. Implemented via ``analysis.loading`` so the ``browser`` value is
    decoded correctly from the ``{country}/{browser}/{hex}/{slug}`` layout.
    """
    from analysis.loading import load_site, site_paths

    paths = site_paths(data_dir)
    if not paths:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")
    for path in paths:
        site = load_site(path, data_dir)
        if site is not None:
            yield site.domain, site.browser, site.data


# One CookieDataset per data_dir, reused across loader calls within a run.
_DATASETS: dict[str, CookieDataset] = {}


def dataset(data_dir: str) -> CookieDataset:
    """Return a memoised :class:`CookieDataset` for ``data_dir``."""
    return _DATASETS.setdefault(data_dir, CookieDataset(data_dir))


def _with_legacy_aliases(cookies: pd.DataFrame, sites: pd.DataFrame):
    """Add the historical column names plot scripts still reference."""
    cookies = cookies.copy()
    sites = sites.copy()
    if "setter_url" in cookies.columns and "set_by_url" not in cookies.columns:
        cookies["set_by_url"] = cookies["setter_url"]
    # site-level aliases (old site_metadata names)
    if "easyprivacy_requests" in sites.columns:
        sites["num_easyprivacy_requests"] = sites["easyprivacy_requests"]
    if "easyprivacy_pct" in sites.columns:
        sites["pct_easyprivacy_requests"] = sites["easyprivacy_pct"]
    if "min_lifetime_days" not in sites.columns:
        sites["min_lifetime_days"] = 0.0
    return cookies, sites


def load_cookie_data(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        sites_df   – one row per (country, browser, site)
        cookies_df – one row per cookie, fully enriched (party_type, is_tracker,
                     entropy, set_by_*, name_family, lifetime_bucket, …)

    Thin wrapper over ``CookieDataset``; column names (incl. legacy aliases like
    ``httpOnly``/``set_by_url``) are preserved for backward compatibility.
    """
    ds = dataset(data_dir)
    cookies, sites = _with_legacy_aliases(ds.cookies, ds.sites)
    return sites, cookies


def load_tracker_cookies(data_dir: str) -> pd.DataFrame:
    """Cookies with a boolean ``is_tracker`` column.

    Tracker status is computed by the dataset (the crawler's ``tracker`` field is
    preferred, otherwise derived from the tracker lists), so this no longer
    requires data pre-annotated by process_cookies.py.
    """
    ds = dataset(data_dir)
    cookies, _ = _with_legacy_aliases(ds.cookies, ds.sites)
    if cookies.empty:
        raise ValueError(f"No cookies found in {data_dir!r}.")
    return cookies


def save_figure(out_dir: str, *filenames: str, facecolor: str = BG) -> None:
    """Save the current figure to one or more files, then close it."""
    os.makedirs(out_dir, exist_ok=True)
    for filename in filenames:
        out_path = os.path.join(out_dir, filename)
        plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=facecolor)
        # Plain ASCII arrow: a Windows cp1252 console cannot encode "→".
        print(f"Saved -> {out_path}")
    plt.close()


# BUCKETS, BUCKET_COLORS and lifetime_bucket are imported from analysis.enrich
# (the canonical definition) at the top of this module and re-exported here so
# plot scripts can keep importing them from utils unchanged.


# ---------------------------------------------------------------------------
# Plotting helpers  (eliminate the boilerplate that repeats across every script)
# ---------------------------------------------------------------------------


def make_parser(
    description: str = "", *, data: str = "./cookies_data", out: str = "./plots"
) -> argparse.ArgumentParser:
    """Return an ArgumentParser pre-loaded with ``--data`` and ``--out``."""
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--data", default=data)
    p.add_argument("--out", default=out)
    return p


def gradient_colors(
    values,
    hue: float = 0.06,
    sat_lo: float = 0.4,
    sat_hi: float = 0.95,
    val_lo: float = 0.9,
    val_hi: float = 0.55,
) -> list[str]:
    """Per-bar HSV gradient colours scaled to the value range (warm orange ramp).

    ``hue=0.06`` is the orange shade used throughout this project. ``sat_lo``/
    ``val_lo`` is the lightest bar (lowest value); ``sat_hi``/``val_hi`` the
    darkest (highest). Returns a list of hex colour strings.
    """
    vals = list(values)
    lo, hi = min(vals), max(vals)
    norm = plt.Normalize(lo, hi) if hi > lo else (lambda v: 0.5)
    return [
        mc.to_hex(
            mc.hsv_to_rgb(
                [
                    hue,
                    sat_lo + (sat_hi - sat_lo) * norm(v),
                    val_lo + (val_hi - val_lo) * norm(v),
                ]
            )
        )
        for v in vals
    ]


def clean_ax(ax, *, grid_axis: str = "x", alpha: float = 0.3) -> None:
    """Remove top/right spines and add a light grid."""
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis=grid_axis, alpha=alpha)


def annotate_hbars(ax, bars, labels, *, offset=None, fontsize: int = 11) -> None:
    """Place text labels just to the right of each horizontal bar.

    ``labels`` is a list of strings (one per bar). ``offset`` defaults to 1 % of
    the widest bar so the spacing scales with the data.
    """
    max_w = max((b.get_width() for b in bars), default=1)
    if offset is None:
        offset = max_w * 0.01
    for bar, lbl in zip(bars, labels):
        ax.text(
            bar.get_width() + offset,
            bar.get_y() + bar.get_height() / 2,
            str(lbl),
            va="center",
            fontsize=fontsize,
            color=DARK,
        )


def hbar_chart(ax, labels, values, *, colors=None, height: float = 0.72):
    """Draw a horizontal bar chart with the highest value at the top.

    Wraps ``ax.barh`` + ``ax.invert_yaxis``; returns the bar container so
    callers can pass it to :func:`annotate_hbars`.
    """
    bars = ax.barh(
        labels, values, color=colors, edgecolor=BG, linewidth=0.6, height=height
    )
    ax.invert_yaxis()
    return bars


def donut_chart(
    ax,
    labels: list[str],
    values: list[float],
    colors: list[str],
    *,
    center_text: str | None = None,
    label_distance: float = 1.28,
    counts: list[int] | None = None,
) -> None:
    """Draw a donut chart with outside leader-line labels.

    ``values`` are percentages (must sum to 100). Optional ``center_text`` is
    placed in the hole. ``counts`` appends ``(n,)`` raw counts to each label.
    """
    wedges = ax.pie(
        values,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.5, "edgecolor": BG, "linewidth": 2},
    )[0]
    if center_text:
        ax.text(
            0,
            0,
            center_text,
            ha="center",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=ACCENT,
        )
    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2
        cos_a = np.cos(np.deg2rad(angle))
        sin_a = np.sin(np.deg2rad(angle))
        lbl = f"{labels[i]}\n{values[i]:.1f}%"
        if counts is not None:
            lbl += f"  ({counts[i]:,})"
        ax.annotate(
            lbl,
            xy=(0.98 * cos_a, 0.98 * sin_a),
            xytext=(label_distance * cos_a, label_distance * sin_a),
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=DARK,
            arrowprops=dict(arrowstyle="-", color=DARK, lw=1.2),
        )
