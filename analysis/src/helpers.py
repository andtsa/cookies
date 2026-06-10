from __future__ import annotations

import hashlib

import tldextract

# total_bits cutoff used to flag a value as "high entropy". ~36 bits is a 12-char
# value with a full distribution, comfortably above structured codes like
# "en_US". Shared by the value-entropy share mode and the syncing candidate
# filter so the threshold lives in one place.
HIGH_ENTROPY_BITS = 36.0

# Lower bar used specifically for the corroborated confirmation rule
# (list match + third-party deployment + capability): when two independent
# strong signals already agree, a value only needs enough bits to plausibly
# carry an identifier — far less than the standalone HIGH_ENTROPY_BITS cutoff.
CORROBORATED_ENTROPY_BITS = 12.0

# Lifetime buckets (ordered) and a matching colour ramp, absorbed from
# plot_scripts/utils.py so the package owns the canonical definition and the
# plot util can re-export it.
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


def registered_domain(url_or_host: str) -> str:
    """Registrable domain of a URL or hostname (``""`` for empty input)."""
    if not url_or_host:
        return ""
    return tldextract.extract(url_or_host).registered_domain or url_or_host


def get_base_domain(hostname: str) -> str:
    """Registrable domain, raising on clearly invalid input.

    Mirrors scripts/process_cookies.py so party-type results are identical.
    """
    if not hostname:
        raise ValueError("Hostname is empty")
    extracted = tldextract.extract(hostname.lstrip("."))
    if not extracted.domain or not extracted.suffix:
        raise ValueError(f"Invalid hostname: {hostname}")
    return f"{extracted.domain}.{extracted.suffix}"


def party_type(target_hostname: str, cookie_domain: str) -> str:
    """Classify a cookie as ``first_party`` / ``third_party`` / ``unknown``.

    A cookie is first-party when it shares the registrable domain of the page it
    was observed on. Invalid/missing domains yield ``"unknown"`` rather than
    raising, so a single bad cookie never aborts a whole-dataset build.
    """
    try:
        return (
            "first_party"
            if get_base_domain(target_hostname.lower())
            == get_base_domain(cookie_domain.lower())
            else "third_party"
        )
    except (ValueError, AttributeError):
        return "unknown"


def lifetime_bucket(days: float | None, is_session: bool) -> str:
    """Bucket a cookie by lifetime; session cookies are their own bucket."""
    if is_session:
        return "Session"
    days = days or 0
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


def md5_value(value: str) -> str:
    """md5 hex digest of a cookie value (stable cross-site identity key)."""
    return hashlib.md5((value or "").encode()).hexdigest()
