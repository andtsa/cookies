"""
client/trackers/entropy.py
--------------------------
Statistical uniqueness analysis for cookie (and request-parameter) values.

The goal is to distinguish high-entropy *unique identifiers* (UIDs) — the
hallmark of a tracking cookie — from low-entropy *functional* values such as
``language=en`` or ``darkMode=true``.

We deliberately expose the raw measurements and do **not** emit a hard
"is this a UID" verdict here. Two complementary metrics are provided:

* ``shannon_entropy`` — Shannon entropy in **bits per character**. Measures how
  random the *character distribution* is, independent of length. A long word
  and a short random token can score similarly, so this is not sufficient alone.
* ``total_bits`` — ``shannon_entropy * length``, i.e. the approximate total
  information content of the string. This separates long UIDs
  (``a7x9f228j991pqzm2`` ~ 60+ bits) from short structured codes (``en_US`` ~
  12 bits), and is the more robust signal for real-world UID detection.

Downstream code (``process_cookies.py``, ``find_shared_cookies.py``,
``find_cookie_syncing.py``) stores both numbers plus the value length and makes
any thresholding decision itself, keeping this module purely descriptive.

Value extraction
----------------
``_extract_id_component`` is a single seam through which every value passes
before measurement. Today it is the identity function (we measure the raw
value, which is fully reproducible and assumption-free). It exists so that a
future, more aggressive isolation step — stripping known structured prefixes
(``GA1.2.``), URL-decoding, or base64-decoding before measuring — can be
introduced in one place without touching any caller.
"""

from __future__ import annotations

import math
from collections import Counter

__all__ = [
    "shannon_entropy",
    "total_bits",
    "value_length",
    "entropy_metrics",
]


def _extract_id_component(value: str) -> str:
    """Return the substring of ``value`` whose entropy we actually measure.

    Identity for now (raw-value measurement). This is the documented seam for a
    future prefix-stripping / decoding step — change it here and every caller
    benefits, with no API change.
    """
    return value


def shannon_entropy(value: str) -> float:
    """Shannon entropy of ``value`` in bits per character.

    Returns 0.0 for empty/non-string input. A string of all-identical
    characters has entropy 0.0; a string with a perfectly uniform character
    distribution approaches ``log2(num_distinct_chars)``.
    """
    if not value:
        return 0.0
    component = _extract_id_component(value)
    if not component:
        return 0.0
    total = len(component)
    freq = Counter(component)
    return -sum(
        (count / total) * math.log2(count / total) for count in freq.values()
    )


def total_bits(value: str) -> float:
    """Approximate total information content: ``shannon_entropy * length``.

    This is the length-aware metric; it is the more reliable signal for telling
    long random UIDs apart from short functional values.
    """
    if not value:
        return 0.0
    component = _extract_id_component(value)
    return shannon_entropy(value) * len(component)


def value_length(value: str) -> int:
    """Length of the measured component (after the extraction seam)."""
    if not value:
        return 0
    return len(_extract_id_component(value))


def entropy_metrics(value: str) -> dict:
    """Convenience bundle of all metrics for one value.

    Returns ``{"entropy", "total_bits", "value_length"}`` rounded for compact,
    diff-friendly JSON. ``entropy`` is bits/char; ``total_bits`` is the
    length-weighted total.
    """
    ent = shannon_entropy(value)
    length = value_length(value)
    return {
        "entropy": round(ent, 4),
        "total_bits": round(ent * length, 4),
        "value_length": length,
    }
