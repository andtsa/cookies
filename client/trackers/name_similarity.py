"""
client/trackers/name_similarity.py
-----------------------------------
Group cookie names into *families* so that obfuscated or per-instance variants
of the same tracker are recognised as one identifier.

Real-world tracker cookies are rarely named identically across sites. Google
Analytics alone produces ``_ga``, ``_gid``, ``_gat``, ``_gat_UA-12345-6``,
``_gat_gtag_UA_12345_6`` …; many trackers append the property/site id or a
random suffix. Matching on exact names (as ``find_shared_cookies.py`` does by
default) therefore misses these.

Strategy (two layers, per the agreed design):

1. **Prefix grouping (primary).** Normalise each name — lowercase, strip a
   trailing ``UA-…``/digit/hex suffix and separators — then key by the
   normalised prefix. This is fast, dependency-light, and mirrors how tracker
   families are actually named (a stable prefix + a variable tail).

2. **Levenshtein tie-break (secondary).** Merge prefix-groups whose
   representative names are within a small edit distance of each other, to catch
   near-misses the normalisation step split apart (e.g. ``_gtag`` vs ``_gat``).
   Uses ``rapidfuzz`` (C-backed) for the distance.

The public entry point is :func:`cluster_names`, which returns a mapping from
each original name to a stable family label (the shortest member of the group).
"""

from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz.distance import Levenshtein

__all__ = ["normalize_name", "cluster_names"]

# Trailing variable tails commonly appended to a stable tracker prefix:
#   _gat_UA-12345-6   -> _gat
#   _gat_gtag_UA_1_2  -> _gat_gtag   (then UA tail stripped)
#   ar_debug.12345    -> ar_debug
# We strip, from the right, runs of: UA-style property ids, digits, hex chunks,
# and the separators joining them.
_UA_SUFFIX_RE = re.compile(r"(?i)[._-]*ua[._-]?[0-9a-z]+([._-][0-9a-z]+)*$")
_TRAILING_TOKEN_RE = re.compile(r"(?i)[._-]+[0-9a-f]{2,}$")
_TRAILING_DIGITS_RE = re.compile(r"[0-9]+$")
# Only trailing separators are stripped — a leading "_" (e.g. "_ga") is part of
# the stable prefix and must be preserved.
_TRAILING_SEPARATORS_RE = re.compile(r"[._-]+$")


def normalize_name(name: str) -> str:
    """Reduce a cookie name to its stable prefix for grouping.

    Lowercases, strips a trailing UA-style property id, then repeatedly peels
    trailing hex/numeric tokens and edge separators. Returns the original
    lowercased name if nothing is strippable, and never returns empty (falls
    back to the lowercased original) so distinct short names stay distinct.
    """
    if not name:
        return ""
    original = name.strip().lower()
    n = _UA_SUFFIX_RE.sub("", original)

    # Peel trailing hex/numeric tokens until stable.
    while True:
        stripped = _TRAILING_TOKEN_RE.sub("", n)
        stripped = _TRAILING_DIGITS_RE.sub("", stripped)
        stripped = _TRAILING_SEPARATORS_RE.sub("", stripped)
        if stripped == n or not stripped:
            break
        n = stripped

    n = _TRAILING_SEPARATORS_RE.sub("", n)
    return n or original


def cluster_names(
    names,
    max_edit_distance: int = 2,
    min_prefix_len: int = 2,
) -> dict[str, str]:
    """Map each name in ``names`` to a stable family label.

    Args:
        names: iterable of cookie-name strings (duplicates allowed).
        max_edit_distance: prefix-groups whose representatives are within this
            Levenshtein distance are merged. Set to 0 to disable the tie-break
            and rely on prefix grouping alone.
        min_prefix_len: prefixes shorter than this are not merged with others
            via edit distance (avoids collapsing unrelated tiny names like
            ``id``/``ad``).

    Returns:
        ``{original_name: family_label}``. The family label is the shortest
        name in the family (ties broken alphabetically) — a stable, readable
        representative.
    """
    unique = sorted({n for n in names if n})
    if not unique:
        return {}

    # Layer 1: bucket by normalised prefix.
    prefix_groups: dict[str, list[str]] = defaultdict(list)
    for name in unique:
        prefix_groups[normalize_name(name)].append(name)

    prefixes = sorted(prefix_groups)

    # Layer 2: union-find merge of prefixes within edit distance.
    parent = {p: p for p in prefixes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    if max_edit_distance > 0:
        for i in range(len(prefixes)):
            pi = prefixes[i]
            if len(pi) < min_prefix_len:
                continue
            for j in range(i + 1, len(prefixes)):
                pj = prefixes[j]
                if len(pj) < min_prefix_len:
                    continue
                # Cheap length gate before the distance computation.
                if abs(len(pi) - len(pj)) > max_edit_distance:
                    continue
                if Levenshtein.distance(pi, pj) <= max_edit_distance:
                    union(pi, pj)

    # Collect final families and choose a stable label per family.
    families: dict[str, list[str]] = defaultdict(list)
    for prefix in prefixes:
        root = find(prefix)
        families[root].extend(prefix_groups[prefix])

    result: dict[str, str] = {}
    for members in families.values():
        label = min(members, key=lambda s: (len(s), s))
        for member in members:
            result[member] = label
    return result
