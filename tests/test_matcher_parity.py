"""
Parity test: the Hyperscan matching engine must agree with the stdlib-``re``
reference engine on real crawl request URLs.

The Hyperscan engine drives tracker labels, so any divergence silently changes
classifications. This test builds both engines from the cached EasyPrivacy list
and asserts identical ``.matched`` verdicts over a corpus of real
``(url, document_url, type)`` triples extracted from a crawl directory.

It is skipped (not failed) when:
  * the ``hyperscan`` extension is unavailable (e.g. Windows/CI without it), or
  * no crawl directory is available to draw a corpus from.

Point it at a crawl with ``ANNOTATE_CRAWL_DIR=/path/to/cookies_data``; otherwise
it tries ``./cookies_data`` under the repo root.

Both engines now share the *same* O(1) host index for domain-anchored rules and
the *same* generated regexes for generic rules (Hyperscan just matches the
generic set in one pass instead of a linear scan), so verdicts are expected to
be identical. Any divergence reported here points at a Hyperscan-vs-``re``
semantic gap in the generic patterns and should be investigated, not tolerated.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_TRACKER_CACHE = os.path.join(_REPO_ROOT, ".tracker_cache")

MAX_TRIPLES = int(os.environ.get("PARITY_MAX_TRIPLES", "20000"))


def _load_filter_list_or_none():
    from client.trackers import Detections, TrackerList

    if not os.path.isdir(_TRACKER_CACHE):
        return None
    tl = TrackerList()
    tl.load(cache_dir=_TRACKER_CACHE, trackers={Detections.EasyPrivacy})
    return tl._easyprivacy if tl._easyprivacy.network_rules else None


def _load_filter_list():
    fl = _load_filter_list_or_none()
    if fl is None:
        pytest.skip(f"no/empty EasyPrivacy list under {_TRACKER_CACHE}")
    return fl


def _crawl_dir() -> str | None:
    cand = os.environ.get("ANNOTATE_CRAWL_DIR") or os.path.join(
        _REPO_ROOT, "cookies_data"
    )
    return cand if os.path.isdir(cand) else None


def _collect_triples(data_dir: str, limit: int) -> list[tuple[str, str, str]]:
    """Unique (url, document_url, type) triples from a crawl directory."""
    from analysis.src.loading import load_site, site_paths
    from analysis.src.progress import bar

    seen: set[tuple[str, str, str]] = set()
    triples: list[tuple[str, str, str]] = []
    pbar = bar(desc="collect triples", total=limit, unit=" triples")
    for path in site_paths(data_dir):
        site = load_site(path, data_dir)
        if site is None:
            continue
        target = site.target_url
        for r in site.requests:
            url = r.get("url", "")
            if not url:
                continue
            key = (url, r.get("document_url", "") or target, r.get("type", ""))
            if key in seen:
                continue
            seen.add(key)
            triples.append(key)
            pbar.update(1)
            if len(triples) >= limit:
                pbar.close()
                return triples
    pbar.close()
    return triples


def test_hyperscan_matches_re_on_real_urls():
    pytest.importorskip("hyperscan", reason="hyperscan extension not installed")

    data_dir = _crawl_dir()
    if data_dir is None:
        pytest.skip(
            "no crawl directory (set ANNOTATE_CRAWL_DIR or extract ./cookies_data)"
        )

    fl = _load_filter_list()
    triples = _collect_triples(data_dir, MAX_TRIPLES)
    if not triples:
        pytest.skip(f"no request URLs found under {data_dir}")

    engine, mismatches = _compare(fl, triples)
    assert engine == "hyperscan", "hyperscan engine failed to build; cannot assert parity"

    if mismatches:
        sample = "\n".join(
            f"  re={r} hs={h}  type={typ!r}  url={url}"
            for url, _, typ, r, h in mismatches[:20]
        )
        pytest.fail(
            f"{len(mismatches)}/{len(triples)} triples diverge between engines:\n{sample}"
        )


def _compare(fl, triples):
    """Run both engines over ``triples``; return ``(engine_name, mismatches)``.

    Shared by the pytest test and the ``__main__`` CLI below.
    """
    from analysis.src.progress import track
    from client.trackers.matcher import EasyPrivacyMatcher

    re_matcher = EasyPrivacyMatcher(fl, "re")
    hs_matcher = EasyPrivacyMatcher(fl, "hyperscan")

    mismatches = []
    for url, doc, typ in track(
        triples, desc="parity match", total=len(triples), unit=" triples"
    ):
        r = re_matcher.match(url, doc, typ).matched
        h = hs_matcher.match(url, doc, typ).matched
        if r != h:
            mismatches.append((url, doc, typ, r, h))
    return hs_matcher.engine_name, mismatches


def _main() -> int:
    """Run the parity check as a plain script so progress bars are visible.

    Unlike ``pytest`` (which captures stderr and hides tqdm), this prints bars
    and a summary directly. Honours the same ``ANNOTATE_CRAWL_DIR`` /
    ``PARITY_MAX_TRIPLES`` env vars.
    """
    try:
        import hyperscan  # noqa: F401
    except Exception:
        print("hyperscan not installed; nothing to compare against the re engine.")
        return 1
    data_dir = _crawl_dir()
    if data_dir is None:
        print("no crawl directory (set ANNOTATE_CRAWL_DIR or extract ./cookies_data).")
        return 1
    fl = _load_filter_list_or_none()
    if fl is None:
        print(f"no/empty EasyPrivacy list under {_TRACKER_CACHE}.")
        return 1

    print(f"collecting up to {MAX_TRIPLES:,} unique triples from {data_dir} ...")
    triples = _collect_triples(data_dir, MAX_TRIPLES)
    if not triples:
        print(f"no request URLs found under {data_dir}.")
        return 1

    engine, mismatches = _compare(fl, triples)
    if engine != "hyperscan":
        print("hyperscan engine failed to build; cannot compare.")
        return 1
    print(f"\n{len(triples):,} triples compared; {len(mismatches):,} mismatch(es).")
    for url, _, typ, r, h in mismatches[:20]:
        print(f"  re={r} hs={h}  type={typ!r}  url={url}")
    return 0 if not mismatches else 2


if __name__ == "__main__":
    raise SystemExit(_main())
