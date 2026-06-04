"""
analysis/analyses.py
--------------------
Built-in named analyses, registered with :func:`analysis.dataset.register`.

Each is a plain function ``fn(dataset, **params) -> pd.DataFrame`` returning a
tidy, plot-ready frame. Adding data prep for a new plot is a one-function change
here (or anywhere that imports ``register``); the plot then calls
``ds.analysis("name")``. Importing this module is what populates the registry,
so :mod:`analysis.__init__` imports it eagerly.

The set below covers the open items in ``additional-analyses.todo.md`` plus the
common reductions the existing plot scripts perform.
"""

from __future__ import annotations

import pandas as pd

from .dataset import register


# ----------------------------------------------------------- cross-dimension
@register("trackers_by_country")
def trackers_by_country(ds) -> pd.DataFrame:
    """Tracker share (% of cookies that are trackers) per crawl country."""
    df = ds.cookies
    out = (
        df.groupby("country")
        .agg(
            cookies=("is_tracker", "size"),
            trackers=("is_tracker", "sum"),
        )
        .reset_index()
    )
    out["tracker_pct"] = (out["trackers"] / out["cookies"] * 100).round(1)
    return out


@register("trackers_by_browser")
def trackers_by_browser(ds) -> pd.DataFrame:
    """Tracker share per browser engine."""
    df = ds.cookies
    out = (
        df.groupby("browser")
        .agg(
            cookies=("is_tracker", "size"),
            trackers=("is_tracker", "sum"),
        )
        .reset_index()
    )
    out["tracker_pct"] = (out["trackers"] / out["cookies"] * 100).round(1)
    return out


@register("sites_with_tracker_pct")
def sites_with_tracker_pct(ds, by: tuple[str, ...] = ("country",)) -> pd.DataFrame:
    """Percentage of sites carrying at least one tracker, grouped by ``by``."""
    cookies = ds.cookies
    site_keys = ["country", "browser", "domain"]
    per_site = (
        cookies.groupby(site_keys)["is_tracker"].any().reset_index(name="has_tracker")
    )
    group = list(by)
    out = (
        per_site.groupby(group)
        .agg(
            sites=("has_tracker", "size"),
            with_tracker=("has_tracker", "sum"),
        )
        .reset_index()
    )
    out["pct_sites_with_tracker"] = (out["with_tracker"] / out["sites"] * 100).round(1)
    return out


@register("trackers_vs_rank")
def trackers_vs_rank(ds) -> pd.DataFrame:
    """Mean tracker share and any-tracker rate per popularity tier."""
    cookies = ds.cookies
    site_keys = ["country", "browser", "domain"]
    per_site = (
        cookies.groupby(site_keys)
        .agg(
            rank_tier=("rank_tier", "first"),
            cookies=("is_tracker", "size"),
            trackers=("is_tracker", "sum"),
        )
        .reset_index()
    )
    per_site["tracker_pct"] = per_site["trackers"] / per_site["cookies"] * 100
    per_site["has_tracker"] = per_site["trackers"] > 0
    out = (
        per_site.groupby("rank_tier")
        .agg(
            sites=("has_tracker", "size"),
            mean_tracker_pct=("tracker_pct", "mean"),
            pct_has_tracker=("has_tracker", "mean"),
        )
        .reset_index()
    )
    out["mean_tracker_pct"] = out["mean_tracker_pct"].round(1)
    out["pct_has_tracker"] = (out["pct_has_tracker"] * 100).round(1)
    return out


@register("trackers_vs_lifetime_by_tld")
def trackers_vs_lifetime_by_tld(ds) -> pd.DataFrame:
    """Per-TLD: tracker share and median persistent lifetime."""
    df = ds.cookies
    persistent = df[~df["session"]]
    out = (
        df.groupby("tld")
        .agg(
            cookies=("is_tracker", "size"),
            trackers=("is_tracker", "sum"),
        )
        .reset_index()
    )
    life = (
        persistent.groupby("tld")["lifetime_days"]
        .median()
        .reset_index(name="median_lifetime_days")
    )
    out = out.merge(life, on="tld", how="left")
    out["tracker_pct"] = (out["trackers"] / out["cookies"] * 100).round(1)
    return out.sort_values("cookies", ascending=False)


@register("first_vs_third_party")
def first_vs_third_party(ds, trackers_only: bool = False) -> pd.DataFrame:
    """First- vs third-party cookie counts (optionally only trackers)."""
    df = ds.cookies
    if trackers_only:
        df = df[df["is_tracker"]]
    out = df.groupby("party_type").size().reset_index(name="value")
    total = out["value"].sum()
    out["pct"] = (out["value"] / total * 100).round(1) if total else 0.0
    return out


# ------------------------------------------------------------- providers / graph
@register("provider_ranking")
def provider_ranking(ds, top_n: int = 20) -> pd.DataFrame:
    """Which tracker providers track the most sites (ranking).

    A "provider" is the registrable setter domain of a tracker cookie; ranked by
    the number of distinct crawled sites it appears on.
    """
    df = ds.cookies[ds.cookies["is_tracker"]].copy()
    df["provider"] = (
        df["setter_domain"]
        .fillna(df["tracker_provider"])
        .fillna(df["registered_domain"])
    )
    df["site"] = df["country"] + "/" + df["browser"] + "/" + df["domain"]
    out = (
        df.groupby("provider")
        .agg(
            sites=("site", "nunique"),
            cookies=("site", "size"),
        )
        .reset_index()
    )
    return out.sort_values("sites", ascending=False).head(top_n)


@register("tracker_site_graph")
def tracker_site_graph(
    ds, top_n: int = 20, category: str | None = None
) -> pd.DataFrame:
    """Bipartite edges: top tracker providers <-> the sites they appear on.

    Returns ``(provider, registered_domain, weight)`` rows for the ``top_n``
    providers (by site reach). Restrict to a website ``category`` (e.g.
    ``"medical"``) for the medical-tracker graph.
    """
    df = ds.cookies[ds.cookies["is_tracker"]].copy()
    if category is not None:
        df = df[df["category"] == category]
    df["provider"] = (
        df["setter_domain"]
        .fillna(df["tracker_provider"])
        .fillna(df["registered_domain"])
    )
    top = (
        df.groupby("provider")["registered_domain"]
        .nunique()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    edges = (
        df[df["provider"].isin(top)]
        .groupby(["provider", "registered_domain"])
        .size()
        .reset_index(name="weight")
    )
    return edges.sort_values("weight", ascending=False)


@register("medical_trackers_outside")
def medical_trackers_outside(ds, top_n: int = 20) -> pd.DataFrame:
    """Trackers seen on medical sites that ALSO appear outside the medical field.

    For each tracker provider active on ``category == "medical"`` sites, report
    how many medical vs non-medical distinct sites it reaches — the cross-field
    spillover the medical analysis asks for.
    """
    df = ds.cookies[ds.cookies["is_tracker"]].copy()
    df["provider"] = (
        df["setter_domain"]
        .fillna(df["tracker_provider"])
        .fillna(df["registered_domain"])
    )
    df["site"] = df["country"] + "/" + df["browser"] + "/" + df["domain"]
    df["is_medical"] = df["category"] == "medical"
    medical_providers = df.loc[df["is_medical"], "provider"].unique()
    sub = df[df["provider"].isin(medical_providers)]
    out = (
        sub.groupby("provider")
        .agg(
            medical_sites=(
                "site",
                lambda s: s[sub.loc[s.index, "is_medical"]].nunique(),
            ),
            nonmedical_sites=(
                "site",
                lambda s: s[~sub.loc[s.index, "is_medical"]].nunique(),
            ),
        )
        .reset_index()
    )
    return out.sort_values("nonmedical_sites", ascending=False).head(top_n)


# ----------------------------------------------------------------- lifetime
@register("lifetime_buckets")
def lifetime_buckets(ds) -> pd.DataFrame:
    """Cookie counts per lifetime bucket (ordered)."""
    from .enrich import BUCKETS

    out = ds.cookies.groupby("lifetime_bucket").size().reset_index(name="value")
    out["lifetime_bucket"] = pd.Categorical(
        out["lifetime_bucket"], categories=BUCKETS, ordered=True
    )
    return out.sort_values("lifetime_bucket")
