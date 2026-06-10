"""Unit tests for the cookie-syncing detector in analysis.src.syncing.

Detection (value matching + the PATH/endpoint regex layer) now lives in the
analysis engine; scripts/find_cookie_syncing.py is only a thin reporting CLI over
it. These tests exercise the engine's ``analyze_site`` / ``PathSyncDetector``.
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from analysis.src import syncing as fcs  # noqa: E402

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


# --- path-sync (endpoint-keyword) detection ------------------------------

_DETECTOR = fcs.PathSyncDetector()


def test_path_detector_token_boundary_no_false_positive():
    # "track" must not fire inside "attachment"; "match" not inside "rematching".
    assert _DETECTOR.match("https://t.com/attachment/file", "t.com") is None
    assert _DETECTOR.match("https://t.com/rematching/x", "t.com") is None


def test_path_detector_matches_hyphenated_token_as_unit():
    ev = _DETECTOR.match("https://t.com/cookie-sync/begin", "t.com")
    assert ev is not None
    assert "cookie-sync" in ev["path_keywords"]
    assert ev["where"] == "path"


def test_path_detector_matches_param_name():
    ev = _DETECTOR.match("https://t.com/x?partner_uid=ABCDEFGH12345678", "t.com")
    assert ev is not None
    assert ev["path_keywords"] == []
    assert "partner_uid" in ev["param_keywords"]
    assert ev["where"] == "param"


def test_path_detector_glob_pattern():
    # Glob "sync*" matches the whole token but respects the leading boundary.
    det = fcs.PathSyncDetector(("sync*",))
    assert det.match("https://t.com/syncing", "t.com")["path_keywords"] == ["syncing"]
    assert "sync_user" in det.match("https://t.com/sync_user", "t.com")["path_keywords"]
    assert det.match("https://t.com/resync", "t.com") is None


def test_glob_to_regex_escapes_metachars():
    # A '.' in a pattern must be literal, not "any char".
    det = fcs.PathSyncDetector(("a.b",))
    assert det.match("https://t.com/a.b/x", "t.com") is not None
    assert det.match("https://t.com/axb/x", "t.com") is None


def _path_annotated(result):
    """All confirmed/candidate rows carrying a path_sync annotation."""
    return [r for r in result["confirmed"] + result["candidates"] if "path_sync" in r]


def test_path_sync_requires_identifier():
    # Endpoint keyword but NO identifier on the request -> nothing to annotate.
    data = _site([{"url": "https://tracker-b.com/usersync?lang=en"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=_DETECTOR)
    assert _path_annotated(result) == []


def test_path_sync_annotates_confirmed_row_as_cookie():
    # Neutral param name "u" so the only endpoint signal is the path.
    data = _site([{"url": f"https://tracker-b.com/usersync?u={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=_DETECTOR)
    assert len(result["confirmed"]) == 1
    ps = result["confirmed"][0]["path_sync"]
    assert "usersync" in ps["path_keywords"]
    assert ps["where"] == "path"
    assert ps["kind"] == "cookie"


def test_path_sync_annotates_candidate_row_as_entropy():
    other = "z9q3w8e7r6t5y4u3i2o1p0"  # high-entropy, not a known cookie
    data = _site([{"url": f"https://tracker-b.com/cookie-sync?u={other}"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=_DETECTOR)
    assert result["confirmed"] == []
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["path_sync"]["kind"] == "entropy"


def test_path_sync_cross_domain_only():
    # Same registered domain is never a sync, even with an identifier.
    data = _site([{"url": f"https://api.news-site.com/usersync?id={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=_DETECTOR)
    assert _path_annotated(result) == []


def test_path_sync_absent_when_detector_disabled():
    data = _site([{"url": f"https://tracker-b.com/usersync?partner_id={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=None)
    assert "path_sync" not in result["confirmed"][0]


def test_path_sync_no_endpoint_leaves_rows_unannotated():
    # Cross-domain confirmed sync, but the URL (path + param name) has no
    # sync-endpoint keyword -> the confirmed row is left unannotated.
    data = _site([{"url": f"https://tracker-b.com/p?u={UID}"}])
    result = fcs.analyze_site(data, min_bits=36.0, path_detector=_DETECTOR)
    assert len(result["confirmed"]) == 1
    assert "path_sync" not in result["confirmed"][0]
