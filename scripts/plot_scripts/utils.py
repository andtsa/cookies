import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.colors as mc
import matplotlib.pyplot as plt

# Make the repo-root ``analysis`` package importable from scripts/plot_scripts/.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "plot_scripts"))
from analysis import (  # noqa: E402,F401
    BUCKET_COLORS,
    BUCKETS,
    CookieDataset,
    lifetime_bucket,
)

BG = "#ffffff"  # "#fef2e6"
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
    """Yield ``(domain, browser, data)`` for every site JSON under ``data_dir``."""
    found = False
    for site in dataset(data_dir).iter_raw_sites():
        found = True
        yield site.domain, site.browser, site.data
    if not found:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")


# Default cap (entries of the ranking list) applied to every plot, overridable
# via the COOKIE_RANK_CAP env var ('none'/'off'/'0' disables capping).
_DEFAULT_RANK_CAP = 100_000


def _resolve_rank_cap() -> int | None:
    raw = os.environ.get("COOKIE_RANK_CAP")
    if raw is None:
        return _DEFAULT_RANK_CAP
    if raw.strip().lower() in {"none", "off", "0", ""}:
        return None
    return int(raw)


def _discover_shards(data_dir: str) -> list[str]:
    """Split ``data_dir`` into ``{country}/{browser}`` shards, if it has them.

    The crawler's canonical layout is ``{country}/{browser}/{hexprefix}/*.json``
    (see :func:`analysis.src.loading.path_context`), so a depth-2 directory is
    one (country, browser) shard — small enough to load raw into memory one at
    a time instead of materialising the whole 100k-site corpus at once. Falls
    back to ``[data_dir]`` (no sharding) for flat/ad-hoc layouts, e.g. test
    fixtures with JSON files directly under ``data_dir``.
    """
    shards = sorted(str(p) for p in Path(data_dir).glob("*/*") if p.is_dir())
    return shards or [data_dir]


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


class _ShardedDataset:
    """Drop-in stand-in for :class:`CookieDataset` over a possibly-huge tree.

    Backs every ``{country}/{browser}`` shard (see :func:`_discover_shards`)
    with its own short-lived :class:`CookieDataset`, so at most one shard's
    raw site JSON (the thing that OOMs at 100k-sites-times-browsers scale) is
    resident at once. Tabular results (``cookies``/``sites``/
    ``classified_cookies``) are concatenated across shards; the relational
    list methods (``shared``/``syncing``/``third_party_reads``/
    ``sync_subtype_rows``/``cross_domain_reads``) are too, which is valid
    because each of them already partitions its work by ``(country, browser)``
    internally (see ``analysis/access/relational.py``) — concatenating
    per-shard results is equivalent to running over the unsharded corpus.

    Exposes only the subset of ``CookieDataset``'s surface that
    ``scripts/plot_scripts/*.py`` actually uses. If a script needs something
    else from ``CookieDataset``, add it here rather than reaching for the
    unsharded class directly.
    """

    _LIST_METHODS = (
        "shared",
        "syncing",
        "third_party_reads",
        "sync_subtype_rows",
        "cross_domain_reads",
    )

    def __init__(self, data_dir: str, *, rank_cap: int | None, n_workers: int):
        self._data_dir = data_dir
        self._rank_cap = rank_cap
        self._n_workers = n_workers
        self._shards = _discover_shards(data_dir)
        self._shard_ds: list[CookieDataset] | None = None
        self._frames: dict[str, pd.DataFrame] = {}
        self._lists: dict[tuple, list[dict]] = {}

    def _shard_datasets(self) -> list[CookieDataset]:
        # Memoized: every accessor below (cookies/sites/classified_cookies/
        # shared/group/iter_raw_sites) must reuse the *same* per-shard
        # CookieDataset, or each one re-parses that shard's raw JSON from
        # scratch instead of reusing the instance's own cached_propertys.
        if self._shard_ds is None:
            self._shard_ds = [
                CookieDataset(
                    shard_dir, rank_cap=self._rank_cap, n_workers=self._n_workers
                )
                for shard_dir in self._shards
            ]
        return self._shard_ds

    @staticmethod
    def _drop_raw(ds: CookieDataset) -> None:
        # Free this shard's raw JSON + per-site EP cache once we've pulled
        # what we need out of it. The CookieDataset instance (and its disk
        # caches) stays, so re-deriving another attribute later is a cheap
        # cache hit, not a re-parse — but the multi-megabyte raw request
        # logs for every site in the shard don't sit in memory indefinitely.
        ds.__dict__.pop("_raw_sites", None)
        ds._ep_cache.clear()

    @property
    def high_entropy_bits(self) -> float:
        # A plain __init__-assigned attribute (not data-derived), so reading
        # it off one throwaway shard instance triggers no raw JSON loading.
        return self._shard_datasets()[0].high_entropy_bits

    def _frame(self, attr: str) -> pd.DataFrame:
        if attr not in self._frames:
            parts = []
            for ds in self._shard_datasets():
                parts.append(getattr(ds, attr))
                self._drop_raw(ds)
            self._frames[attr] = (
                pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            )
        return self._frames[attr]

    @property
    def cookies(self) -> pd.DataFrame:
        return self._frame("cookies")

    @property
    def sites(self) -> pd.DataFrame:
        return self._frame("sites")

    @property
    def classified_cookies(self) -> pd.DataFrame:
        return self._frame("classified_cookies")

    def iter_raw_sites(self):
        for ds in self._shard_datasets():
            yield from ds.iter_raw_sites()
            self._drop_raw(ds)

    def _merged_list(self, method: str, kwargs: dict) -> list[dict]:
        key = (method, tuple(sorted(kwargs.items())))
        if key not in self._lists:
            rows: list[dict] = []
            for ds in self._shard_datasets():
                rows.extend(getattr(ds, method)(**kwargs))
                self._drop_raw(ds)
            self._lists[key] = rows
        return self._lists[key]

    def shared(self, **kwargs) -> list[dict]:
        return self._merged_list("shared", kwargs)

    def syncing(self, **kwargs) -> list[dict]:
        return self._merged_list("syncing", kwargs)

    def third_party_reads(self) -> list[dict]:
        return self._merged_list("third_party_reads", {})

    def sync_subtype_rows(self, **kwargs) -> list[dict]:
        return self._merged_list("sync_subtype_rows", kwargs)

    def cross_domain_reads(self, **kwargs) -> list[dict]:
        return self._merged_list("cross_domain_reads", kwargs)

    def group(
        self,
        by: list[str],
        metric: str = "count",
        *,
        where: dict | None = None,
        trackers_only: bool = False,
        df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Mirrors :meth:`analysis.access.aggregate.AggregateAccess.group`,
        run against the merged frames instead of a single CookieDataset's."""
        if df is not None:
            frame = df
        elif trackers_only:
            frame = self.classified_cookies
        else:
            frame = self.cookies
        if where:
            for col, val in (where or {}).items():
                frame = frame[frame[col] == val]
        if trackers_only:
            frame = frame[frame["is_tracker"]]
        grouped = frame.groupby(by, dropna=False)
        if metric == "count":
            return grouped.size().reset_index(name="value")
        if metric.startswith("nunique:"):
            col = metric.split(":", 1)[1]
            return grouped[col].nunique().reset_index(name="value")
        agg, col = metric.split(":", 1)
        return grouped[col].agg(agg).reset_index(name="value")


# One _ShardedDataset per (data_dir, rank_cap), reused across loader calls
# within a run. Keyed on the resolved cap too so changing COOKIE_RANK_CAP
# mid-process yields a fresh instance rather than a stale, differently-capped
# one.
_DATASETS: dict[tuple[str, int | None], "_ShardedDataset"] = {}


def dataset(data_dir: str) -> "_ShardedDataset":
    """Return a memoised dataset facade for ``data_dir``.

    Capped to the first ``COOKIE_RANK_CAP`` (default 100,000) ranked sites; set
    that env var to ``none`` to analyse the full crawl.

    Splits ``data_dir`` into ``{country}/{browser}`` shards (see
    :func:`_discover_shards`) and loads/holds at most one shard's raw site
    JSON at a time — the corpus's raw request logs are what blow up memory at
    100k-sites-times-browsers scale, not the resulting tabular frames. Run
    ``scripts/annotate.py`` once per shard beforehand so each shard's
    ``CookieDataset`` build here is a cheap parquet-cache hit rather than a
    cold raw-JSON parse.
    """
    n_workers = (os.cpu_count() or 8) - 1
    rank_cap = _resolve_rank_cap()
    return _DATASETS.setdefault(
        (data_dir, rank_cap),
        _ShardedDataset(data_dir, rank_cap=rank_cap, n_workers=n_workers),
    )


def load_cookie_data(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        sites_df   – one row per (country, browser, site)
        cookies_df – one row per cookie, fully enriched (party_type, is_tracker,
                     tracker_tier, tracker_signals, entropy, set_by_*, …)

    ``is_tracker`` is the unified classification-based boolean
    (``tracker_tier >= "probable"``), not a raw list-match. All plot scripts
    that filter or aggregate on ``is_tracker`` therefore use the same definition,
    whether they go through this loader or access ``ds.classified_cookies``
    directly.
    """
    ds = dataset(data_dir)
    cookies, sites = _with_legacy_aliases(ds.classified_cookies, ds.sites)
    return sites, cookies


def load_tracker_cookies(data_dir: str) -> pd.DataFrame:
    """Cookies where ``is_tracker`` is True (``tracker_tier >= "probable"``).

    Uses :attr:`~analysis.CookieDataset.classified_cookies` so the boolean
    reflects the full behavioural classification, not just list membership.
    """
    ds = dataset(data_dir)
    cookies, _ = _with_legacy_aliases(ds.classified_cookies, ds.sites)
    if cookies.empty:
        raise ValueError(f"No cookies found in {data_dir!r}.")
    return cookies


def filter_country_browser(
    df: pd.DataFrame,
    country: str | None = None,
    browser: str | None = None,
) -> pd.DataFrame:
    """Case-insensitive filter of a cookies/sites frame by country and/or browser.

    Either dimension is skipped when its argument is falsy or the literal
    ``"all"`` (so callers can expose ``--country all`` / ``--browser all`` to
    opt out). Unknown columns are ignored. Returns a view/copy-safe subset; the
    caller should ``.copy()`` if it intends to mutate.
    """
    out = df
    if country and str(country).lower() != "all" and "country" in out.columns:
        out = out[out["country"].astype(str).str.lower() == str(country).lower()]
    if browser and str(browser).lower() != "all" and "browser" in out.columns:
        out = out[out["browser"].astype(str).str.lower() == str(browser).lower()]
    return out


def load_health_domains(csv_path: str) -> set[str]:
    """Read the health-site list into a set of bare, lower-cased domains."""
    df = pd.read_csv(csv_path)
    return set(
        df["domain"].astype(str).str.strip().str.lower().str.removeprefix("www.")
    )


def save_figure(out_dir: str, *filenames: str, facecolor: str = BG) -> None:
    """Save the current figure to one or more files, then close it."""
    os.makedirs(out_dir, exist_ok=True)
    for filename in filenames:
        out_path = os.path.join(out_dir, filename)
        plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=facecolor)
        print(f"Saved -> {out_path}")
    plt.close()


# BUCKETS, BUCKET_COLORS and lifetime_bucket are re-exported from analysis
# (the canonical definition) at the top of this module and re-exported here so
# plot scripts can keep importing them from utils unchanged.


# ---------------------------------------------------------------------------
# Plotting helpers
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
