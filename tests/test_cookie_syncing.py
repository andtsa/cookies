"""Unit tests for scripts/find_cookie_syncing.py analyze_site()."""

import importlib.util
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

# Load the script module by path (scripts/ is not a package).
_spec = importlib.util.spec_from_file_location(
    "find_cookie_syncing",
    os.path.join(ROOT, "scripts", "find_cookie_syncing.py"),
)
fcs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcs)


UID = "a7x9f228j991pqzm2c4b8"


def _site(requests):
    return {
        "target_url": "https://news-site.com/",
        "cookies": [{"name": "uid", "value": UID}],
        "requests": requests,
    }


def test_confirmed_sync_cross_domain():
    data = _site([{"url": f"https://tracker-b.com/sync?partner_id={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0)
    assert len(result["confirmed"]) == 1
    ev = result["confirmed"][0]
    assert ev["cookie_name"] == "uid"
    assert ev["to_domain"] == "tracker-b.com"
    assert ev["param"] == "partner_id"


def test_same_domain_is_not_a_sync():
    # Value sent to the SAME registered domain is not cookie syncing.
    data = _site([{"url": f"https://api.news-site.com/track?id={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0)
    assert result["confirmed"] == []


def test_url_encoded_value_is_matched():
    from urllib.parse import quote

    encoded = quote(UID, safe="")
    data = _site([{"url": f"https://tracker-b.com/s?u={encoded}"}])
    result = fcs.analyze_site(data, min_bits=36.0)
    assert len(result["confirmed"]) == 1


def test_high_entropy_candidate_flagged():
    # An unknown high-entropy value sent cross-domain is a candidate, not confirmed.
    other = "z9q3w8e7r6t5y4u3i2o1p0"
    data = _site([{"url": f"https://tracker-b.com/s?x={other}"}])
    result = fcs.analyze_site(data, min_bits=36.0)
    assert result["confirmed"] == []
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["to_domain"] == "tracker-b.com"


def test_low_entropy_param_ignored():
    data = _site([{"url": "https://tracker-b.com/s?lang=en&debug=true"}])
    result = fcs.analyze_site(data, min_bits=36.0)
    assert result["confirmed"] == []
    assert result["candidates"] == []


# --- deep-match (base64 + substring) -------------------------------------


def test_base64_encoded_value_only_matched_in_deep_mode():
    import base64

    enc = base64.b64encode(UID.encode()).decode()
    data = _site([{"url": f"https://tracker-b.com/s?u={enc}"}])

    shallow = fcs.analyze_site(data, min_bits=36.0, deep=False)
    assert shallow["confirmed"] == []  # missed without deep

    deep = fcs.analyze_site(data, min_bits=36.0, deep=True)
    assert len(deep["confirmed"]) == 1
    assert deep["confirmed"][0]["cookie_name"] == "uid"


def test_param_base64_decoding_to_value_matched_in_deep_mode():
    # The site cookie holds a base64 string; a partner sends its decoded bytes.
    import base64

    raw_id = "ABCDEFGH12345678"  # 16 chars, decodes/encodes cleanly
    b64_cookie = base64.b64encode(raw_id.encode()).decode()
    data = {
        "target_url": "https://news-site.com/",
        "cookies": [{"name": "vid", "value": b64_cookie}],
        "requests": [{"url": f"https://tracker-b.com/s?p={raw_id}"}],
    }
    deep = fcs.analyze_site(data, min_bits=36.0, deep=True)
    assert any(ev["cookie_name"] == "vid" for ev in deep["confirmed"])


def test_embedded_substring_match_deep_only():
    # UID embedded inside a larger param value.
    data = _site([{"url": f"https://tracker-b.com/s?p=prefix_{UID}_suffix"}])

    shallow = fcs.analyze_site(data, min_bits=36.0, deep=False)
    assert shallow["confirmed"] == []

    deep = fcs.analyze_site(data, min_bits=36.0, deep=True)
    assert len(deep["confirmed"]) == 1
    assert deep["confirmed"][0]["match"] == "substring"


def test_deep_does_not_break_exact_match_kind():
    data = _site([{"url": f"https://tracker-b.com/sync?partner_id={UID}"}])
    deep = fcs.analyze_site(data, min_bits=36.0, deep=True)
    assert len(deep["confirmed"]) == 1
    assert deep["confirmed"][0]["match"] == "exact"
