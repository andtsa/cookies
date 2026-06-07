"""
Cross-site shared-cookie detection, from scripts/find_shared_cookies.py

Operates on *occurrence dicts* (one per cookie, projected from the enriched
frame) rather than re-reading files, so it shares the dataset's single parse and
its already-computed name families.
"""

from __future__ import annotations

from collections import defaultdict

from .helpers import HIGH_ENTROPY_BITS


def build_index(
    occurrences: list[dict],
    match_mode: str,
    families: dict[str, str] | None = None,
) -> dict[tuple, list[dict]]:
    """Group occurrences into ``key -> [occurrence, ...]`` per match mode.

    Keys are tuples so the reducer can render them uniformly:
      name-md5      -> ("name", <name>, <md5>)
      value-entropy -> ("value", <md5>)
      name-cluster  -> ("cluster", <family>, <md5>)

    ``name-cluster`` reuses the dataset's precomputed ``families`` mapping
    (``{name: family}``) instead of re-clustering, so labels stay stable.
    """
    index: dict[tuple, list[dict]] = defaultdict(list)

    if match_mode == "name-md5":
        for occ in occurrences:
            index[("name", occ["name"], occ["md5_value"])].append(occ)
    elif match_mode == "value-entropy":
        for occ in occurrences:
            if occ.get("total_bits", 0.0) >= HIGH_ENTROPY_BITS:
                index[("value", occ["md5_value"])].append(occ)
    elif match_mode == "name-cluster":
        families = families or {}
        for occ in occurrences:
            family = families.get(occ["name"], occ["name"])
            index[("cluster", family, occ["md5_value"])].append(occ)
    else:
        raise ValueError(f"Unknown match mode: {match_mode}")

    return index


def _label_for_key(key: tuple) -> str:
    if key[0] == "name":
        return key[1]
    if key[0] == "cluster":
        return f"{key[1]} (family)"
    return "<high-entropy value>"


def find_shared(
    index: dict[tuple, list[dict]],
    min_sites: int = 2,
    trackers_only: bool = False,
    third_party_only: bool = False,
) -> list[dict]:
    """Reduce the index to cross-site groups, annotated with party info."""
    results: list[dict] = []

    for key, occurrences in index.items():
        sites_seen: dict[str, dict] = {}
        for occ in occurrences:
            sites_seen.setdefault(occ["site"], occ)

        if len(sites_seen) < min_sites:
            continue

        occs = list(sites_seen.values())
        party_types = [o.get("party_type", "unknown") for o in occs]
        has_third_party = any(p == "third_party" for p in party_types)

        if third_party_only and not has_third_party:
            continue
        if trackers_only and not any(bool(o.get("is_tracker")) for o in occs):
            continue

        results.append(
            {
                "key_type": key[0],
                "label": _label_for_key(key),
                "md5_value": key[-1],
                "site_count": len(sites_seen),
                "distinct_first_parties": sum(
                    1 for p in party_types if p == "first_party"
                ),
                "has_third_party": has_third_party,
                "any_tracker": any(bool(o.get("is_tracker")) for o in occs),
                "domains": sorted({o.get("registered_domain", "") for o in occs}),
                "sites": [
                    {
                        "site": o["site"],
                        "registered_domain": o.get("registered_domain", ""),
                        "country": o.get("country", ""),
                        "browser": o.get("browser", ""),
                        "cookie_type": o.get("cookie_type", ""),
                        "party_type": o.get("party_type", "unknown"),
                        "name": o["name"],
                        "is_tracker": bool(o.get("is_tracker")),
                    }
                    for o in sorted(occs, key=lambda x: x["site"])
                ],
            }
        )

    results.sort(key=lambda r: r["site_count"], reverse=True)
    return results
