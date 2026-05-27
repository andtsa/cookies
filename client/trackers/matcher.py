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


class EasyPrivacyMatcher:
    """
    Fast matcher for Adblock Plus network rules.

    Domain-anchored rules (||domain^) are indexed by hostname for O(1) lookup.
    Generic pattern rules are compiled to regexes and scanned linearly.
    Exception rules (@@) are indexed the same way and checked after a block match.

    Build once; reuse across all page visits.
    """

    def __init__(self, filter_list: FilterList):
        # domain → [block rules whose pattern anchors to that domain]
        self._block_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        # compiled (regex, rule) for non-domain-anchored block rules
        self._block_generic: list[tuple[re.Pattern, NetworkRule]] = []

        # same structure for exception rules
        self._except_domain_idx: dict[str, list[NetworkRule]] = defaultdict(list)
        self._except_generic: list[tuple[re.Pattern, NetworkRule]] = []

        self._build(filter_list)
        print(
            f"EasyPrivacyMatcher ready: "
            f"{sum(len(v) for v in self._block_domain_idx.values())} domain-indexed rules, "
            f"{len(self._block_generic)} generic rules, "
            f"{sum(len(v) for v in self._except_domain_idx.values())} exception domain rules, "
            f"{len(self._except_generic)} exception generic rules."
        )

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build(self, fl: FilterList) -> None:
        for rule in fl.block_rules:
            domain = self._anchor_domain(rule.pattern)
            if domain:
                self._block_domain_idx[domain].append(rule)
            else:
                try:
                    self._block_generic.append((rule.to_regex(), rule))
                except re.error:
                    pass  # skip malformed patterns

        for rule in fl.exception_rules:
            domain = self._anchor_domain(rule.pattern)
            if domain:
                self._except_domain_idx[domain].append(rule)
            else:
                try:
                    self._except_generic.append((rule.to_regex(), rule))
                except re.error:
                    pass

    @staticmethod
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
            self._block_domain_idx,
            self._block_generic,
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
            self._except_domain_idx,
            self._except_generic,
        )
        if except_rule is not None:
            return MatchResult(
                matched=False, blocked_by=block_rule, excepted_by=except_rule
            )

        return MatchResult(matched=True, blocked_by=block_rule)

    def _find_matching_rule(
        self,
        url: str,
        host: str,
        page_domain: str,
        is_3p: bool,
        abp_type: ContentType | None,
        domain_idx: dict[str, list[NetworkRule]],
        generic: list[tuple[re.Pattern, NetworkRule]],
    ) -> NetworkRule | None:
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

        # Among candidates, apply option filters
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
