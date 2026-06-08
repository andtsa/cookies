import os
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import tldextract

from .abp import FilterList, NetworkRule, ContentType

# Maps CDP request type strings to ABP ContentType enum values
CDP_TYPE_TO_ABP: dict[str, ContentType] = {
    "XHR": ContentType.XMLHTTPREQUEST,
    "Fetch": ContentType.XMLHTTPREQUEST,
    "Script": ContentType.SCRIPT,
    "Image": ContentType.IMAGE,
    "Stylesheet": ContentType.STYLESHEET,
    "Ping": ContentType.PING,
    "Media": ContentType.MEDIA,
    "Font": ContentType.FONT,
    "Document": ContentType.DOCUMENT,
    "SubDocument": ContentType.SUBDOCUMENT,
    "WebSocket": ContentType.WEBSOCKET,
    "Other": ContentType.OTHER,
}


@dataclass
class MatchResult:
    matched: bool
    blocked_by: Optional[NetworkRule] = None  # the matching block rule
    excepted_by: Optional[NetworkRule] = None  # the @@ rule that cancelled it

    def to_dict(self) -> dict:
        if not self.matched:
            return {"matched": False}
        return {
            "matched": True,
            "pattern": self.blocked_by.pattern if self.blocked_by else None,
            "excepted": self.excepted_by.pattern if self.excepted_by else None,
        }


class _NullBar:
    """No-op stand-in matching the slice of the tqdm API used below."""

    def update(self, n: int = 1) -> None:
        pass

    def close(self) -> None:
        pass


def _bar(total: int, desc: str):
    """Optional tqdm progress bar; a no-op stand-in when tqdm is absent.

    Kept self-contained (no import from ``analysis``) so ``client`` stays a
    lower-level package with tqdm as a soft, optional dependency.
    """
    try:
        from tqdm.auto import tqdm
    except Exception:
        return _NullBar()
    return tqdm(total=total, desc=desc, unit=" rules", leave=False)


def _anchor_domain(pattern: str) -> str | None:
    """
    Extract the bare hostname from a domain-anchored pattern like
    ||analytics.example.com^ or ||tracker.io^$third-party.

    Returns None if the pattern isn't a clean domain anchor (i.e. it
    contains wildcards or path components that require regex matching).
    """
    if not pattern.startswith("||"):
        return None
    # Strip || and everything from the first ^ / * / ? / /
    body = pattern[2:]
    m = re.match(r"^([\w\-.]+)", body)
    if not m:
        return None
    candidate = m.group(1).lower()
    # Reject if it still contains wildcards or looks like a partial path
    if "*" in candidate or not re.match(r"^[\w\-]+(?:\.[\w\-]+)+$", candidate):
        return None
    return candidate


# ---------------------------------------------------------------------------
# Matching engines
#
# An engine answers one page-independent question: "which rules in this set
# *could* match (url, host)?" — the expensive half of matching. The two engines
# below are interchangeable and MUST return the same candidate sets (validated
# by tests/test_matcher_parity.py); EasyPrivacyMatcher layers the page-dependent
# `_options_match` filter and the (host, url) memo on top of either one.
# ---------------------------------------------------------------------------


class _ReEngine:
    """Stdlib-``re`` engine: domain-anchored rules indexed by hostname for O(1)
    lookup, generic rules compiled to regexes and scanned linearly.

    This is the long-standing reference implementation and the parity baseline.
    """

    def __init__(self, filter_list: FilterList) -> None:
        self._block_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        self._block_generic: list[tuple[re.Pattern, NetworkRule]] = []
        self._except_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        self._except_generic: list[tuple[re.Pattern, NetworkRule]] = []
        self._build(filter_list)

    def _build(self, fl: FilterList) -> None:
        block, exception = fl.block_rules, fl.exception_rules
        pbar = _bar(len(block) + len(exception), "build re engine")
        for rule in block:
            domain = _anchor_domain(rule.pattern)
            if domain:
                self._block_domain_idx[domain].append(rule)
            else:
                try:
                    self._block_generic.append((rule.to_regex(), rule))
                except re.error:
                    pass  # skip malformed patterns
            pbar.update(1)
        for rule in exception:
            domain = _anchor_domain(rule.pattern)
            if domain:
                self._except_domain_idx[domain].append(rule)
            else:
                try:
                    self._except_generic.append((rule.to_regex(), rule))
                except re.error:
                    pass
            pbar.update(1)
        pbar.close()

    def stats(self) -> str:
        return (
            f"{sum(len(v) for v in self._block_domain_idx.values())} domain-indexed rules, "
            f"{len(self._block_generic)} generic rules, "
            f"{sum(len(v) for v in self._except_domain_idx.values())} exception domain rules, "
            f"{len(self._except_generic)} exception generic rules"
        )

    @staticmethod
    def _candidates(
        url: str,
        host: str,
        domain_idx: dict[str, list[NetworkRule]],
        generic: list[tuple[re.Pattern, NetworkRule]],
    ) -> list[NetworkRule]:
        # Walk up the hostname hierarchy: sub.example.com → example.com → com
        parts = host.split(".")
        candidates: list[NetworkRule] = []
        for i in range(len(parts) - 1):
            candidate_host = ".".join(parts[i:])
            candidates.extend(domain_idx.get(candidate_host, []))
        # Add generic rules
        for pattern, rule in generic:
            if pattern.search(url):
                candidates.append(rule)
        return candidates

    def block_candidates(self, url: str, host: str) -> list[NetworkRule]:
        return self._candidates(
            url, host, self._block_domain_idx, self._block_generic
        )

    def except_candidates(self, url: str, host: str) -> list[NetworkRule]:
        return self._candidates(
            url, host, self._except_domain_idx, self._except_generic
        )


# Bump when the serialised-DB payload semantics change (e.g. which rules go into
# the DB and what its ids index) so stale blobs from an older layout are ignored.
_HSDB_VERSION = 2


def _hsdb_path(cache_dir: str, key: str, tag: str) -> str:
    return os.path.join(cache_dir, f"ep_hsdb.v{_HSDB_VERSION}.{key}.{tag}.bin")


def _load_hsdb(cache_dir: str | None, key: str | None, tag: str) -> dict | None:
    if not (cache_dir and key):
        return None
    path = _hsdb_path(cache_dir, key, tag)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as fh:
            data = pickle.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_hsdb(cache_dir: str | None, key: str | None, tag: str, payload: dict) -> None:
    if not (cache_dir and key):
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = _hsdb_path(cache_dir, key, tag)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    except Exception:
        pass  # best-effort; recompiling is always correct


class _HyperscanEngine:
    """Hyperscan engine for the *generic* rules only.

    Domain-anchored rules (``||host^``) keep the same O(1) hostname hash index as
    :class:`_ReEngine` — that lookup is already optimal and, crucially, compiling
    all ~50k rules into one Hyperscan database proved pathologically slow (a huge,
    uninterruptible C-level compile). Only the ~3.5k *generic* rules — the set
    that :class:`_ReEngine` scans linearly, i.e. the actual bottleneck — are
    compiled into a Hyperscan database (one for block rules, one for exceptions)
    and matched in a single pass per URL.

    Patterns Hyperscan rejects at compile time (a small minority — e.g. ones that
    can match an empty buffer) are routed to a residual stdlib-``re`` list, so
    coverage — and therefore parity with :class:`_ReEngine` — never depends on
    full Hyperscan acceptance. The compiled databases are serialised to disk
    (keyed by the EasyPrivacy ruleset fingerprint) so worker processes load a
    prebuilt DB instead of recompiling.

    Construction raises ``ImportError`` when the ``hyperscan`` extension is not
    available (e.g. on Windows); callers fall back to :class:`_ReEngine`.
    """

    def __init__(
        self,
        filter_list: FilterList,
        *,
        cache_dir: str | None = None,
        ruleset_key: str | None = None,
    ) -> None:
        import hyperscan  # noqa: F401 — raises ImportError on unsupported platforms

        self._hs = hyperscan
        self._flags = hyperscan.HS_FLAG_CASELESS | hyperscan.HS_FLAG_SINGLEMATCH

        # Partition each rule set exactly like _ReEngine: domain-anchored → host
        # index (O(1)); everything else → generic, handed to Hyperscan.
        self._block_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        self._except_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        self._block_generic_rules: list[NetworkRule] = []
        self._except_generic_rules: list[NetworkRule] = []
        for rule in filter_list.block_rules:
            domain = _anchor_domain(rule.pattern)
            (self._block_domain_idx[domain].append(rule) if domain
             else self._block_generic_rules.append(rule))
        for rule in filter_list.exception_rules:
            domain = _anchor_domain(rule.pattern)
            (self._except_domain_idx[domain].append(rule) if domain
             else self._except_generic_rules.append(rule))

        self._block_db, self._block_residual = self._build_set(
            self._block_generic_rules, cache_dir, ruleset_key, "block-gen"
        )
        self._except_db, self._except_residual = self._build_set(
            self._except_generic_rules, cache_dir, ruleset_key, "except-gen"
        )
        self._block_scratch = (
            hyperscan.Scratch(self._block_db) if self._block_db is not None else None
        )
        self._except_scratch = (
            hyperscan.Scratch(self._except_db) if self._except_db is not None else None
        )

    # -- construction -------------------------------------------------------

    def _build_set(
        self,
        rules: list[NetworkRule],
        cache_dir: str | None,
        key: str | None,
        tag: str,
    ):
        """Return ``(database_or_None, residual)`` for one rule set.

        ``residual`` is a list of ``(compiled_re, rule)`` for rules Hyperscan
        could not accept. Rule *ids* are indices into ``rules`` (stable for a
        given ruleset fingerprint), so the disk cache only needs to record which
        ids were residual.
        """
        if not rules:
            return None, []

        cached = _load_hsdb(cache_dir, key, tag)
        if cached is not None:
            try:
                db = self._hs.loadb(cached["db"])
                residual = self._residual_from_ids(rules, cached["residual_ids"])
                return db, residual
            except Exception:
                pass  # fall through to a fresh build

        db, residual_ids = self._compile(rules, tag)
        residual = self._residual_from_ids(rules, residual_ids)
        if db is not None:
            _save_hsdb(
                cache_dir,
                key,
                tag,
                {"db": self._hs.dumpb(db), "residual_ids": residual_ids},
            )
        return db, residual

    @staticmethod
    def _residual_from_ids(
        rules: list[NetworkRule], residual_ids: list[int]
    ) -> list[tuple[re.Pattern, NetworkRule]]:
        residual: list[tuple[re.Pattern, NetworkRule]] = []
        for i in residual_ids:
            try:
                residual.append((rules[i].to_regex(), rules[i]))
            except re.error:
                pass
        return residual

    def _compile(self, rules: list[NetworkRule], tag: str = ""):
        """Compile ``rules`` into one Hyperscan DB; return ``(db, residual_ids)``."""
        exprs = [r.to_regex_str().encode("utf-8", "ignore") for r in rules]
        ids = list(range(len(rules)))
        good = self._validate(exprs, ids, tag)
        residual_ids = [i for i in ids if i not in good]
        if not good:
            return None, residual_ids
        gi = sorted(good)
        db = self._hs.Database()
        db.compile(
            expressions=[exprs[i] for i in gi],
            ids=gi,
            elements=len(gi),
            flags=[self._flags] * len(gi),
        )
        return db, residual_ids

    def _validate(self, exprs: list[bytes], ids: list[int], tag: str = "") -> set[int]:
        """Return the ids whose expressions Hyperscan accepts.

        Tries a bulk compile first; on failure bisects to isolate the offending
        expressions, so the per-pattern cost is paid only around real rejects.
        The progress bar advances as ids are resolved (a clean bulk compile fills
        it in one jump; heavy bisection over incompatible patterns shows it
        crawling — itself a useful signal that the residual ``re`` list is big).
        """
        good: set[int] = set()
        pbar = _bar(len(ids), f"hyperscan compile [{tag}]")

        def attempt(idx_list: list[int]) -> None:
            if not idx_list:
                return
            try:
                tmp = self._hs.Database()
                tmp.compile(
                    expressions=[exprs[i] for i in idx_list],
                    ids=idx_list,
                    elements=len(idx_list),
                    flags=[self._flags] * len(idx_list),
                )
                good.update(idx_list)
                pbar.update(len(idx_list))
            except Exception:
                if len(idx_list) == 1:
                    pbar.update(1)  # single offending pattern → residual
                    return
                mid = len(idx_list) // 2
                attempt(idx_list[:mid])
                attempt(idx_list[mid:])

        attempt(ids)
        pbar.close()
        return good

    def stats(self) -> str:
        block_idx = sum(len(v) for v in self._block_domain_idx.values())
        except_idx = sum(len(v) for v in self._except_domain_idx.values())
        block_db = len(self._block_generic_rules) - len(self._block_residual)
        except_db = len(self._except_generic_rules) - len(self._except_residual)
        return (
            f"{block_idx} domain-indexed rules, "
            f"{block_db} generic rules in HS db (+{len(self._block_residual)} residual re), "
            f"{except_idx} exception domain rules, "
            f"{except_db} exception generic in HS db (+{len(self._except_residual)} residual re)"
        )

    # -- scanning -----------------------------------------------------------

    def _candidates(
        self,
        url: str,
        host: str,
        domain_idx: dict[str, list[NetworkRule]],
        db,
        scratch,
        generic_rules: list[NetworkRule],
        residual: list[tuple[re.Pattern, NetworkRule]],
    ) -> list[NetworkRule]:
        # Domain-anchored rules: walk the hostname hierarchy (same as _ReEngine).
        parts = host.split(".")
        candidates: list[NetworkRule] = []
        for i in range(len(parts) - 1):
            candidates.extend(domain_idx.get(".".join(parts[i:]), []))

        # Generic rules: one Hyperscan pass returns all matching ids.
        if db is not None:
            matched_ids: list[int] = []

            def on_match(rid, frm, to, flags, ctx):
                ctx.append(rid)
                return None

            db.scan(
                url.encode("utf-8", "ignore"),
                match_event_handler=on_match,
                scratch=scratch,
                context=matched_ids,
            )
            candidates.extend(generic_rules[i] for i in matched_ids)
        for pattern, rule in residual:
            if pattern.search(url):
                candidates.append(rule)
        return candidates

    def block_candidates(self, url: str, host: str) -> list[NetworkRule]:
        return self._candidates(
            url, host, self._block_domain_idx, self._block_db,
            self._block_scratch, self._block_generic_rules, self._block_residual,
        )

    def except_candidates(self, url: str, host: str) -> list[NetworkRule]:
        return self._candidates(
            url, host, self._except_domain_idx, self._except_db,
            self._except_scratch, self._except_generic_rules, self._except_residual,
        )


def _build_engine(
    filter_list: FilterList,
    engine: str,
    cache_dir: str | None,
    ruleset_key: str | None,
):
    """Resolve the requested engine name to ``(active_name, engine_obj)``.

    ``hyperscan`` falls back to ``re`` (with a printed notice) whenever the
    extension is unavailable or the database fails to build — so the same code
    runs on a Linux server (Hyperscan) and a Windows dev box (re) unchanged.
    """
    name = (engine or "hyperscan").lower()
    if name in ("hyperscan", "vectorscan", "hs"):
        try:
            return "hyperscan", _HyperscanEngine(
                filter_list, cache_dir=cache_dir, ruleset_key=ruleset_key
            )
        except Exception as exc:  # ImportError on Windows, build errors elsewhere
            print(
                f"[EasyPrivacyMatcher] hyperscan unavailable ({exc!r}); "
                f"falling back to the 're' engine"
            )
            return "re", _ReEngine(filter_list)
    return "re", _ReEngine(filter_list)


class EasyPrivacyMatcher:
    """
    Fast matcher for Adblock Plus network rules.

    Candidate-rule lookup is delegated to a pluggable engine (``re`` or
    ``hyperscan``; see :func:`_build_engine`). On top of the engine this class
    adds the page-dependent option filter (:meth:`_options_match`) and a
    per-instance ``(host, url)`` memo for the page-independent candidate set —
    the expensive part that depends only on the request, never on the
    page/document context, so it's safe to cache for the matcher's lifetime.

    Build once; reuse across all page visits.
    """

    def __init__(
        self,
        filter_list: FilterList,
        engine: str = "hyperscan",
        *,
        cache_dir: str | None = None,
        ruleset_key: str | None = None,
    ):
        # Memo for the page-independent half of rule matching (block + exception
        # kept separate since they're independent rule sets).
        self._block_candidate_cache: dict[tuple[str, str], list[NetworkRule]] = {}
        self._except_candidate_cache: dict[tuple[str, str], list[NetworkRule]] = {}

        self.engine_name, self._engine = _build_engine(
            filter_list, engine, cache_dir, ruleset_key
        )
        print(
            f"EasyPrivacyMatcher ready (engine={self.engine_name}): "
            f"{self._engine.stats()}."
        )

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match(
        self,
        request_url: str,
        page_url: str,
        cdp_type: str = "",
    ) -> MatchResult:
        """
        Check whether request_url should be blocked according to EasyPrivacy.

        Args:
            request_url: The URL being requested.
            page_url:    The top-level document URL (from CDP documentURL).
            cdp_type:    CDP request type string ("Script", "XHR", "Image", …).

        Returns:
            MatchResult with matched=True only when a block rule fires AND
            no exception rule cancels it.
        """
        request_ext = tldextract.extract(request_url)
        page_ext = tldextract.extract(page_url)
        request_host = request_ext.fqdn.lower()  # full hostname
        page_domain = page_ext.registered_domain  # eTLD+1 of the page
        is_3p = request_ext.registered_domain != page_ext.registered_domain
        abp_type = CDP_TYPE_TO_ABP.get(cdp_type)

        block_rule = self._find_matching_rule(
            request_url,
            request_host,
            page_domain,
            is_3p,
            abp_type,
            self._engine.block_candidates,
            self._block_candidate_cache,
        )
        if block_rule is None:
            return MatchResult(matched=False)

        # Check whether an exception rule cancels this block
        except_rule = self._find_matching_rule(
            request_url,
            request_host,
            page_domain,
            is_3p,
            abp_type,
            self._engine.except_candidates,
            self._except_candidate_cache,
        )
        if except_rule is not None:
            return MatchResult(
                matched=False, blocked_by=block_rule, excepted_by=except_rule
            )

        return MatchResult(matched=True, blocked_by=block_rule)

    def _candidate_rules(
        self,
        url: str,
        host: str,
        candidates_fn,
        cache: dict[tuple[str, str], list[NetworkRule]],
    ) -> list[NetworkRule]:
        """Rules that *could* match this request, ignoring page context.

        Memoised on ``(host, url)``: the same tracker request recurs across many
        different pages/content-types, all sharing this candidate set even
        though their final verdicts (computed by the cheap ``_options_match``
        filter below) may differ.
        """
        key = (host, url)
        cached = cache.get(key)
        if cached is not None:
            return cached
        candidates = candidates_fn(url, host)
        cache[key] = candidates
        return candidates

    def _find_matching_rule(
        self,
        url: str,
        host: str,
        page_domain: str,
        is_3p: bool,
        abp_type: ContentType | None,
        candidates_fn,
        candidate_cache: dict[tuple[str, str], list[NetworkRule]],
    ) -> NetworkRule | None:
        candidates = self._candidate_rules(url, host, candidates_fn, candidate_cache)

        # Among candidates, apply the cheap, page-dependent option filters.
        for rule in candidates:
            if self._options_match(rule, page_domain, is_3p, abp_type):
                return rule
        return None

    @staticmethod
    def _options_match(
        rule: NetworkRule,
        page_domain: str,
        is_3p: bool,
        abp_type: ContentType | None,
    ) -> bool:
        opts = rule.options

        # third-party filter
        if opts.third_party is True and not is_3p:
            return False
        if opts.third_party is False and is_3p:
            return False

        # domain filter
        if opts.domain_includes:
            if not any(
                page_domain == d or page_domain.endswith("." + d)
                for d in opts.domain_includes
            ):
                return False
        if opts.domain_excludes:
            if any(
                page_domain == d or page_domain.endswith("." + d)
                for d in opts.domain_excludes
            ):
                return False

        # content type filter
        if abp_type and opts.content_types_include:
            if abp_type not in opts.content_types_include:
                return False
        if abp_type and opts.content_types_exclude:
            if abp_type in opts.content_types_exclude:
                return False

        return True
