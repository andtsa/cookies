"""
Tiered "looks like / behaves like a tracker" classification.

Combines the dataset's per-cookie signals (list-based detection, entropy,
lifetime, party/setter context) with cross-site behavioural evidence (shared
identifiers, confirmed cookie syncing, cross-domain JS reads) into a single
ordinal label. The design deliberately favours *flagging capability* over
*trusting declarations*: a persistent, high-entropy cookie is labelled at
least "possible" even with zero observed cross-site behaviour, and
site-declared attributes that would normally suppress suspicion (``httpOnly``,
``SameSite=Strict``) are NOT used as counter-evidence, since they only constrain
*how* a cookie could be used to track (JS-readable vs. server-side-only,
cross-site-sendable or not), not *whether* it can. A server can correlate
visits via an httpOnly identifier just as easily as a JS-readable one; the
promise is made by the same party being evaluated.

Tiers (ordinal — each level implies everything below it):

  confirmed  Direct behavioural proof (the value was observed being passed to
             a different domain, e.g. cookie syncing) or multiple independent
             strong signals corroborating each other (list match + third-party
             deployment + identifying capability; or the same identifier
             reused across several distinct third-party contexts).

  probable   One strong, fairly unambiguous signal: a known-tracker-list
             match, the identifier showing up on multiple distinct sites, the
             name being read by JS across multiple domains, or a third-party
             setter combined with capability and a long lifetime.

  possible   Capability alone, with no corroboration yet: a value that *could*
             serve as a stable cross-visit identifier (high entropy +
             persistent), or simply being deployed by a third party (a context
             that enables (without proving) cross-site tracking).

  none       Nothing tracking-relevant fired: short-lived, low-entropy,
             first-party-set, not list-matched, not observed cross-site.

Thresholds are module-level constants so they can be tuned without touching
the rule logic, and every fired rule is recorded in ``tracker_signals`` so the
label is auditable rather than a black box.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .helpers import HIGH_ENTROPY_BITS

# tiers
NONE = "none"
POSSIBLE = "possible"
PROBABLE = "probable"
CONFIRMED = "confirmed"

TIERS = [NONE, POSSIBLE, PROBABLE, CONFIRMED]
_TIER_RANK = {tier: i for i, tier in enumerate(TIERS)}

# thresholds

# "Survives across visits" — the minimum lifetime for a cookie to plausibly
# re-identify a returning user at all.
PERSISTENT_MIN_DAYS = 1.0
# Long enough to be a deliberate cross-session identifier rather than an
# auth/session-extension cookie that happens to outlive a single visit.
LONG_LIVED_MIN_DAYS = 30.0
# Cross-site identifier-reuse thresholds (site_count from ``shared_groups``).
SHARED_SITES_PROBABLE = 2
SHARED_SITES_CONFIRMED = 4
# Distinct domains a cookie *name* must be JS-read on to count as cross-domain
# read behaviour (from ``cross_domain_reads``).
CROSS_DOMAIN_READ_DOMAINS = 2


@dataclass(frozen=True)
class _Evidence:
    """Cross-site evidence, pre-indexed for O(1) per-cookie lookup."""

    # (country, browser, site_domain) -> {cookie_name, ...} confirmed-synced on that crawl
    synced_names: dict[tuple[str, str, str], frozenset[str]] = field(
        default_factory=dict
    )
    # (country, browser, md5_value) -> the largest matching shared-identifier
    # group summary *within that single crawl* — see note on pooling below.
    shared_by_md5: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    # (country, browser, cookie_name) -> distinct domain count it was JS-read
    # on, within that single crawl.
    cross_domain_reads_by_name: dict[tuple[str, str, str], int] = field(
        default_factory=dict
    )


def _index_evidence(
    shared_groups: list[dict] | None,
    sync_events: list[dict] | None,
    cross_domain_reads: list[dict] | None,
) -> _Evidence:
    """Pre-index the three relational passes for O(1) per-cookie lookup.

    All three are scoped to a single ``(country, browser)`` crawl — not pooled
    across the whole dataset. This matters because the crawl is laid out as
    ``{country}/{browser}/{site}``: the *same* physical website is re-visited
    once per country×browser combination, so a persistent identifier that
    merely survives those re-visits would otherwise look like genuine
    cross-site sharing / cross-domain reads (inflating ``site_count`` /
    ``domain_count`` without any real cross-site behaviour). Keying evidence by
    ``(country, browser, ...)`` and looking it up via the cookie's own crawl
    keeps each crawl's signal self-contained, matching :meth:`syncing`'s
    (already per-crawl) scoping. ``shared_groups``/``cross_domain_reads`` are
    expected to already be partitioned per crawl — see
    ``RelationalAccess.shared``/``RelationalAccess.cross_domain_reads``.
    """
    synced: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for ev in sync_events or []:
        key = (ev.get("country", ""), ev.get("browser", ""), ev.get("domain", ""))
        for hit in ev.get("confirmed") or []:
            name = hit.get("cookie_name")
            if name:
                synced[key].add(name)

    shared_by_md5: dict[tuple[str, str, str], dict[str, Any]] = {}
    for group in shared_groups or []:
        md5 = group.get("md5_value")
        if not md5:
            continue
        key = (group.get("country", ""), group.get("browser", ""), md5)
        prev = shared_by_md5.get(key)
        if prev is None or group.get("site_count", 0) > prev.get("site_count", 0):
            shared_by_md5[key] = group

    read_counts: dict[tuple[str, str, str], int] = {}
    for entry in cross_domain_reads or []:
        name = entry.get("cookie_name")
        if not name:
            continue
        key = (entry.get("country", ""), entry.get("browser", ""), name)
        count = entry.get("domain_count") or len(entry.get("domains") or ())
        read_counts[key] = max(read_counts.get(key, 0), count)

    return _Evidence(
        synced_names={k: frozenset(v) for k, v in synced.items()},
        shared_by_md5=shared_by_md5,
        cross_domain_reads_by_name=read_counts,
    )


def _classify_row(
    row: dict, evidence: _Evidence, high_entropy_bits: float
) -> tuple[str, list[str]]:
    tier = NONE
    signals: list[str] = []

    def fire(min_tier: str, signal: str) -> None:
        nonlocal tier
        signals.append(signal)
        if _TIER_RANK[min_tier] > _TIER_RANK[tier]:
            tier = min_tier

    lifetime_days = row.get("lifetime_days") or 0.0
    is_persistent = row.get("cookie_type") == "persistent"
    capable = (row.get("total_bits") or 0.0) >= high_entropy_bits and (
        is_persistent and lifetime_days >= PERSISTENT_MIN_DAYS
    )
    long_lived_capable = capable and lifetime_days >= LONG_LIVED_MIN_DAYS
    third_party_set = bool(row.get("set_by_third_party"))
    listed = bool(row.get("is_tracker_ep")) or bool(row.get("is_tracker_ocd"))

    country = row.get("country", "")
    browser = row.get("browser", "")
    site_key = (country, browser, row.get("domain", ""))
    was_synced = row.get("name") in evidence.synced_names.get(site_key, frozenset())

    shared = evidence.shared_by_md5.get((country, browser, row.get("md5_value")))
    shared_sites = shared.get("site_count", 0) if shared else 0
    shared_has_3p = bool(shared.get("has_third_party")) if shared else False

    read_domains = evidence.cross_domain_reads_by_name.get(
        (country, browser, row.get("name", "")), 0
    )

    # capability: the cookie *could* track on its own structure/context
    if capable:
        fire(POSSIBLE, "capability:high_entropy+persistent")
    if third_party_set:
        fire(POSSIBLE, "context:set_by_third_party")

    # corroboration
    if listed:
        provider = row.get("tracker_provider") or "list_match"
        fire(PROBABLE, f"list:{provider}")
    if shared_sites >= SHARED_SITES_PROBABLE and shared_has_3p:
        fire(PROBABLE, f"behaviour:identifier_shared_across_{shared_sites}_sites")
    if read_domains >= CROSS_DOMAIN_READ_DOMAINS:
        fire(PROBABLE, f"behaviour:js_read_across_{read_domains}_domains")
    if third_party_set and long_lived_capable:
        fire(PROBABLE, "context:third_party+long_lived+capable")

    # proof
    if was_synced:
        fire(CONFIRMED, "behaviour:cookie_syncing_confirmed")
    if shared_sites >= SHARED_SITES_CONFIRMED and shared_has_3p:
        fire(CONFIRMED, f"behaviour:identifier_shared_across_{shared_sites}_sites")
    if listed and third_party_set and capable:
        fire(CONFIRMED, "corroborated:list+third_party+capability")

    return tier, signals


def classify_cookies(
    cookies_df: pd.DataFrame,
    *,
    shared_groups: list[dict] | None = None,
    sync_events: list[dict] | None = None,
    cross_domain_reads: list[dict] | None = None,
    high_entropy_bits: float = HIGH_ENTROPY_BITS,
) -> pd.DataFrame:
    """Classify every row of ``cookies_df`` into a tiered tracker label.

    Returns a frame aligned to ``cookies_df.index`` with three columns:

    - ``tracker_tier``      ordered category in ``none < possible < probable < confirmed``
    - ``tracker_like``      bool, ``tracker_tier != "none"``
    - ``tracker_signals``   list[str] of every rule that fired
    """
    idx = cookies_df.index
    if cookies_df.empty:
        return pd.DataFrame(
            {
                "tracker_tier": pd.Categorical([], categories=TIERS, ordered=True),
                "tracker_like": pd.Series([], dtype="bool"),
                "tracker_signals": pd.Series([], dtype="object"),
            },
            index=idx,
        )

    evidence = _index_evidence(shared_groups, sync_events, cross_domain_reads)

    tiers: list[str] = []
    signal_lists: list[list[str]] = []
    for row in cookies_df.to_dict("records"):
        tier, signals = _classify_row(row, evidence, high_entropy_bits)
        tiers.append(tier)
        signal_lists.append(signals)

    return pd.DataFrame(
        {
            "tracker_tier": pd.Categorical(tiers, categories=TIERS, ordered=True),
            "tracker_like": [t != NONE for t in tiers],
            "tracker_signals": signal_lists,
        },
        index=idx,
    )
