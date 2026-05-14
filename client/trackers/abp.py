"""
adblock_parser.py
~~~~~~~~~~~~~~~~~
Parser for Adblock Plus / uBlock Origin filter list format (.txt).

Produces a FilterList dataclass containing typed rule objects — one
subclass per rule kind — plus structured metadata from the file header.

Supported rule types
--------------------
  NetworkRule      — URL pattern rules (||domain^, generic paths, @@exceptions)
  ElementHideRule  — CSS-selector hiding rules  (##selector)
  ScriptletRule    — JS injection rules          (##+js(...))
  CspRule          — Content-Security-Policy injection ($csp=...)
  CommentLine      — Lines beginning with !
  MetadataLine     — Key: Value comment lines in the file header

Usage
-----
    from adblock_parser import parse_file, parse_text

    fl = parse_file("easyprivacy.txt")
    print(fl.metadata)          # {"Title": "EasyPrivacy", "Version": ..., ...}
    print(len(fl.rules))        # total parsed rules
    print(fl.summary())         # counts by type

    # Access specific rule types
    for rule in fl.network_rules:
        if rule.is_exception:
            print(rule.pattern, rule.options.domain_includes)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RuleType(Enum):
    NETWORK = auto()  # URL block/allow rules
    ELEMENT_HIDE = auto()  # ##selector  /  #@#selector (exception)
    SCRIPTLET = auto()  # ##+js(...)
    CSP = auto()  # $csp=... (no URL pattern, just a header injection)
    COMMENT = auto()  # ! free-text comment
    METADATA = auto()  # ! Key: Value header line


class ContentType(Enum):
    """Maps to Adblock Plus $option names for request types."""

    SCRIPT = "script"
    IMAGE = "image"
    STYLESHEET = "stylesheet"
    OBJECT = "object"
    XMLHTTPREQUEST = "xmlhttprequest"
    SUBDOCUMENT = "subdocument"
    PING = "ping"
    WEBSOCKET = "websocket"
    MEDIA = "media"
    FONT = "font"
    OTHER = "other"
    DOCUMENT = "document"


# All recognised $option names that are simple boolean flags
_BOOLEAN_OPTIONS: frozenset[str] = frozenset(
    {
        "third-party",
        "~third-party",
        "first-party",
        "~first-party",
        "important",
        "genericblock",
        "~genericblock",
        "generichide",
        "~generichide",
        "inline-script",
        "popup",
        "elemhide",
    }
)

# $option names that map to ContentType values
_CONTENT_TYPE_OPTIONS: frozenset[str] = frozenset(
    ct.value for ct in ContentType
) | frozenset("~" + ct.value for ct in ContentType)


# ---------------------------------------------------------------------------
# Options dataclass (the part after $ in a network rule)
# ---------------------------------------------------------------------------


@dataclass
class RuleOptions:
    """
    Parsed representation of the comma-separated options after '$' in a rule.

    Examples
    --------
    ``$script,xmlhttprequest,domain=~biletomat.pl|~facebook.com``
    ``$third-party,domain=example.com|~exception.com``
    ``$redirect=noop.js,script,important``
    """

    # --- Request-type filters ---
    content_types_include: list[ContentType] = field(default_factory=list)
    """Types the rule *applies to* (empty = all types)."""
    content_types_exclude: list[ContentType] = field(default_factory=list)
    """Types the rule explicitly *ignores*."""

    # --- Party filters ---
    third_party: bool | None = None
    """
    True  → only third-party requests.
    False → only first-party requests.
    None  → both.
    """

    # --- Domain filters ---
    domain_includes: list[str] = field(default_factory=list)
    """Rule applies only on these domains."""
    domain_excludes: list[str] = field(default_factory=list)
    """Rule does NOT apply on these domains."""

    # --- Modifiers ---
    important: bool = False
    """Cannot be overridden by an @@ exception rule."""

    redirect: str | None = None
    """Serve this named stub resource instead of blocking (e.g. ``noop.js``)."""

    redirect_rule: bool = False
    """Like redirect but only fires when another rule already blocks the URL."""

    csp: str | None = None
    """Inject this Content-Security-Policy directive."""

    rewrite: str | None = None
    """Rewrite the response to this ABP resource (e.g. ``abp-resource:blank-js``)."""

    method: str | None = None
    """Restrict to this HTTP method (e.g. ``POST``)."""

    remove: bool = False
    """Remove the matched resource entirely (uBO-specific)."""

    genericblock: bool | None = None
    """True = apply genericblock; False = ~genericblock."""

    unknown_options: list[str] = field(default_factory=list)
    """Any options the parser did not recognise."""


def _parse_options(options_str: str) -> RuleOptions:
    """Parse the comma-separated option string into a RuleOptions object."""
    opts = RuleOptions()

    # Options can themselves contain commas inside values like csp=child-src 'none'; ...
    # so we split carefully: split on commas that are NOT inside a value with spaces.
    # In practice, only `csp=` values contain semicolons; we split on commas that
    # are not preceded by an unfinished `csp=` value.
    tokens = _split_options(options_str)

    for token in tokens:
        token = token.strip()
        if not token:
            continue

        lower = token.lower()

        # --- domain= ---
        if lower.startswith("domain="):
            domains_raw = token[7:]
            for d in domains_raw.split("|"):
                d = d.strip()
                if not d:
                    continue
                if d.startswith("~"):
                    opts.domain_excludes.append(d[1:])
                else:
                    opts.domain_includes.append(d)

        # --- redirect= / redirect-rule ---
        elif lower.startswith("redirect="):
            opts.redirect = token[9:]
        elif lower == "redirect-rule":
            opts.redirect_rule = True

        # --- csp= ---
        elif lower.startswith("csp="):
            opts.csp = token[4:]

        # --- rewrite= ---
        elif lower.startswith("rewrite="):
            opts.rewrite = token[8:]

        # --- method= ---
        elif lower.startswith("method="):
            opts.method = token[7:].upper()

        # --- remove ---
        elif lower == "remove":
            opts.remove = True

        # --- important ---
        elif lower == "important":
            opts.important = True

        # --- third-party / first-party ---
        elif lower in ("third-party", "third_party"):
            opts.third_party = True
        elif lower in ("~third-party", "~third_party", "first-party", "first_party"):
            opts.third_party = False
        elif lower in ("~first-party", "~first_party"):
            opts.third_party = True  # same semantic

        # --- genericblock ---
        elif lower == "genericblock":
            opts.genericblock = True
        elif lower == "~genericblock":
            opts.genericblock = False

        # --- content type options ---
        elif lower.lstrip("~") in {ct.value for ct in ContentType}:
            negated = lower.startswith("~")
            ct_name = lower.lstrip("~")
            ct = ContentType(ct_name)
            if negated:
                opts.content_types_exclude.append(ct)
            else:
                opts.content_types_include.append(ct)

        # --- anything else ---
        else:
            opts.unknown_options.append(token)

    return opts


def _split_options(s: str) -> list[str]:
    """
    Split an option string on commas, but keep ``csp=...`` values intact
    (they contain semicolons and spaces but not bare commas).
    Simple approach: scan for ``csp=`` and treat the rest of that token as
    part of the value until the next recognised option name starts.
    """
    # A 'csp=' value runs until the next comma followed by a recognised keyword.
    # Easiest: split on comma + lookahead for known prefixes.
    _KNOWN_STARTS = re.compile(
        r",(?=(?:~?(?:script|image|stylesheet|object|xmlhttprequest|subdocument|"
        r"ping|websocket|media|font|other|document|third.party|first.party|"
        r"important|genericblock|generichide|redirect|csp=|rewrite=|method=|"
        r"remove|domain=|popup|elemhide|inline.script)))",
        re.IGNORECASE,
    )
    return _KNOWN_STARTS.split(s)


# ---------------------------------------------------------------------------
# Rule dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NetworkRule:
    """
    A URL-pattern network rule — the most common kind.

    Covers:
    * Domain-anchored blocks: ``||analytics.example.com^``
    * Generic path/substring blocks: ``/track.gif?``, ``&t=pageview&``
    * Exception (whitelist) rules: ``@@||safe.example.com^``

    Attributes
    ----------
    raw : str
        The original unmodified line.
    is_exception : bool
        True when the line started with ``@@``.
    pattern : str
        The URL-matching pattern with anchors/wildcards intact but without
        the leading ``@@``, so it can be compiled to a regex independently.
    is_domain_anchor : bool
        True when pattern starts with ``||`` (most common).
    is_start_anchor : bool
        True when pattern starts with ``|`` (but not ``||``).
    is_end_anchor : bool
        True when pattern ends with ``|``.
    has_separator : bool
        True when pattern contains ``^`` (separator wildcard).
    has_wildcard : bool
        True when pattern contains ``*``.
    options : RuleOptions
        Parsed filter options (from the ``$…`` suffix).
    """

    raw: str
    is_exception: bool
    pattern: str
    is_domain_anchor: bool
    is_start_anchor: bool
    is_end_anchor: bool
    has_separator: bool
    has_wildcard: bool
    options: RuleOptions
    rule_type: RuleType = field(default=RuleType.NETWORK, init=False)

    def to_regex(self) -> re.Pattern:
        """
        Compile the pattern to a Python regex.

        Handles ``||``, ``|``, ``^``, and ``*`` wildcards.
        Returns a compiled, case-insensitive pattern.
        """
        p = self.pattern
        # Strip anchors — we handle them explicitly
        start = ""
        end = ""

        if p.startswith("||"):
            # Domain anchor: match start of domain (after scheme)
            start = r"^(?:https?://)?(?:[^/]*\.)?"
            p = p[2:]
        elif p.startswith("|"):
            start = "^"
            p = p[1:]

        if p.endswith("|"):
            end = "$"
            p = p[:-1]

        # Escape regex metacharacters except * and ^
        p = re.sub(r"([.+?{}()\[\]\\])", r"\\\1", p)
        # ^ → separator wildcard
        p = p.replace("^", r"(?:[/?&=;]|$)")
        # * → wildcard
        p = p.replace("*", ".*")

        return re.compile(start + p + end, re.IGNORECASE)


@dataclass
class ElementHideRule:
    """
    A CSS element-hiding rule.

    Syntax: ``[domains]##selector`` or ``[domains]#@#selector`` (exception).

    Attributes
    ----------
    raw : str
    is_exception : bool
        True for ``#@#`` (un-hide) rules.
    selector : str
        The raw CSS selector, e.g. ``.ad-banner``, ``#cxense-recs``.
    applies_to : list[str]
        Domains where the rule is active (empty = all domains).
    excludes : list[str]
        Domains where the rule is suppressed (prefixed with ``~`` in source).
    """

    raw: str
    is_exception: bool
    selector: str
    applies_to: list[str]
    excludes: list[str]
    rule_type: RuleType = field(default=RuleType.ELEMENT_HIDE, init=False)


@dataclass
class ScriptletRule:
    """
    A scriptlet injection rule (``##+js(...)``).

    These inject a named trusted-JS snippet into the page at runtime.
    Used to override JS APIs, set cookies, clear storage, etc.

    Attributes
    ----------
    raw : str
    scriptlet_name : str
        The name of the scriptlet to run, e.g. ``set-cookie``, ``set``.
    arguments : list[str]
        Arguments passed to the scriptlet (comma-separated inside the parens,
        after the name).
    applies_to : list[str]
        Domains where this scriptlet fires.
    excludes : list[str]
        Domains where it is suppressed.
    """

    raw: str
    scriptlet_name: str
    arguments: list[str]
    applies_to: list[str]
    excludes: list[str]
    rule_type: RuleType = field(default=RuleType.SCRIPTLET, init=False)


@dataclass
class CspRule:
    """
    A bare CSP injection rule (no URL pattern — applies site-wide).

    Syntax: ``$csp=child-src 'none'; ...,domain=example.com``

    Attributes
    ----------
    raw : str
    csp_value : str
        The CSP directive string.
    options : RuleOptions
        Parsed options (mainly ``domain=``).
    """

    raw: str
    csp_value: str
    options: RuleOptions
    rule_type: RuleType = field(default=RuleType.CSP, init=False)


@dataclass
class CommentLine:
    """
    A comment or section-header line (starts with ``!``).

    Attributes
    ----------
    raw : str
    text : str
        The comment text with the leading ``! `` stripped.
    is_section_header : bool
        True when the text is a visual separator like ``--- Foo ---``.
    """

    raw: str
    text: str
    is_section_header: bool
    rule_type: RuleType = field(default=RuleType.COMMENT, init=False)


@dataclass
class MetadataLine:
    """
    A ``! Key: Value`` header line at the top of the file.

    Attributes
    ----------
    raw : str
    key : str
        e.g. ``Title``, ``Version``, ``Expires``.
    value : str
        e.g. ``EasyPrivacy``, ``202605081050``.
    """

    raw: str
    key: str
    value: str
    rule_type: RuleType = field(default=RuleType.METADATA, init=False)


# Union type for all rules
AnyRule = (
    NetworkRule | ElementHideRule | ScriptletRule | CspRule | CommentLine | MetadataLine
)


# ---------------------------------------------------------------------------
# FilterList — the top-level result
# ---------------------------------------------------------------------------


@dataclass
class FilterList:
    """
    The parsed result of an Adblock Plus filter list file.

    Attributes
    ----------
    metadata : dict[str, str]
        Key/value pairs from the file header (Title, Version, Expires, …).
    rules : list[AnyRule]
        Every parsed rule in file order (includes comments).
    parse_errors : list[tuple[int, str, str]]
        ``(line_number, raw_line, error_message)`` for any lines that failed.
    """

    metadata: dict[str, str]
    rules: list[AnyRule]
    parse_errors: list[tuple[int, str, str]]

    def __init__(
        self,
        metadata: dict[str, str] = {},
        rules: list[AnyRule] = [],
        parse_errors: list[tuple[int, str, str]] = [],
    ) -> None:
        self.metadata = metadata
        self.rules = rules
        self.parse_errors = parse_errors

    # --- Filtered views (properties for convenience) ---

    @property
    def network_rules(self) -> list[NetworkRule]:
        return [r for r in self.rules if isinstance(r, NetworkRule)]

    @property
    def block_rules(self) -> list[NetworkRule]:
        return [r for r in self.network_rules if not r.is_exception]

    @property
    def exception_rules(self) -> list[NetworkRule]:
        return [r for r in self.network_rules if r.is_exception]

    @property
    def element_hide_rules(self) -> list[ElementHideRule]:
        return [r for r in self.rules if isinstance(r, ElementHideRule)]

    @property
    def scriptlet_rules(self) -> list[ScriptletRule]:
        return [r for r in self.rules if isinstance(r, ScriptletRule)]

    @property
    def csp_rules(self) -> list[CspRule]:
        return [r for r in self.rules if isinstance(r, CspRule)]

    @property
    def comments(self) -> list[CommentLine]:
        return [r for r in self.rules if isinstance(r, CommentLine)]

    # --- Summary ---

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.rules),
            "network_block": len(self.block_rules),
            "network_allow": len(self.exception_rules),
            "element_hide": len(self.element_hide_rules),
            "scriptlet": len(self.scriptlet_rules),
            "csp": len(self.csp_rules),
            "comment": len(self.comments),
            "parse_errors": len(self.parse_errors),
        }

    # --- Lookup helpers ---

    def rules_for_domain(self, domain: str) -> list[AnyRule]:
        """
        Return all rules that explicitly mention *domain* in their domain
        filter (includes or excludes).  Does not perform full URL matching.
        """
        results: list[AnyRule] = []
        for r in self.rules:
            if isinstance(r, NetworkRule):
                all_domains = r.options.domain_includes + r.options.domain_excludes
            elif isinstance(r, (ElementHideRule, ScriptletRule)):
                all_domains = r.applies_to + r.excludes
            elif isinstance(r, CspRule):
                all_domains = r.options.domain_includes + r.options.domain_excludes
            else:
                continue
            if any(domain in d for d in all_domains):
                results.append(r)
        return results

    def match_url(self, url: str) -> list[NetworkRule]:
        """
        Return all NetworkRules whose pattern matches *url*.

        Exception rules (@@) are included in the result — the caller can
        check ``rule.is_exception`` to decide how to apply them.

        Note: this is a convenience method, not a full ad-blocker engine.
        It does not resolve exception-vs-block priority.
        """
        return [r for r in self.network_rules if r.to_regex().search(url)]


# ---------------------------------------------------------------------------
# Parser internals
# ---------------------------------------------------------------------------

# Metadata header pattern: "! Key: Value"
_META_RE = re.compile(r"^!\s+([A-Za-z][A-Za-z0-9 _-]*):\s+(.+)$")
# Section header: "! --- ... ---" or "! *** ... ***" etc.
_SECTION_RE = re.compile(r"^[!\-*=\s]{3,}$")

# Element-hide / scriptlet separator:  ##  #@#  #?#  #$#  ##+js
# We match the full separator so we know which kind we have.
_HIDE_SEP_RE = re.compile(r"(#\?#|#@#|##\+js\(|##|#\$#)")

# Bare CSP rule: starts with "$csp="
_BARE_CSP_RE = re.compile(r"^\$csp=", re.IGNORECASE)


def _parse_domain_list(raw: str) -> tuple[list[str], list[str]]:
    """Split ``a.com,~b.com`` into ([a.com], [b.com])."""
    includes, excludes = [], []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("~"):
            excludes.append(part[1:])
        else:
            includes.append(part)
    return includes, excludes


def _split_pattern_options(line: str) -> tuple[str, str]:
    """
    Split ``pattern$options`` into ``(pattern, options)``.

    The ``$`` separator must not be inside a CSS selector or scriptlet body.
    We find the last ``$`` that is followed by a known option keyword.
    """
    # Walk backwards to find the options-separating $
    # Strategy: look for $ not followed by content that looks like a URL char sequence
    _OPTION_START = re.compile(
        r"\$(~?(?:script|image|stylesheet|object|xmlhttprequest|subdocument|"
        r"ping|websocket|media|font|other|document|third.party|first.party|"
        r"important|genericblock|generichide|redirect|csp|rewrite|method|"
        r"remove|domain|popup|elemhide|inline.script))",
        re.IGNORECASE,
    )
    m = None
    for m in _OPTION_START.finditer(line):
        pass  # find last match
    if m:
        idx = m.start()
        return line[:idx], line[idx + 1 :]
    return line, ""


def _parse_line(line: str, in_header: bool) -> AnyRule | None:
    """
    Parse a single non-empty line and return the appropriate rule object,
    or None if the line should be silently skipped (e.g. blank lines).
    """
    raw = line

    # --- Comments and metadata ---
    if line.startswith("!"):
        text = line[1:].strip()
        if in_header:
            m = _META_RE.match(line)
            if m:
                return MetadataLine(
                    raw=raw, key=m.group(1).strip(), value=m.group(2).strip()
                )
        is_section = bool(re.search(r"[-*=]{3,}", text))
        return CommentLine(raw=raw, text=text, is_section_header=is_section)

    # --- Bare CSP rules ($csp=...) ---
    if _BARE_CSP_RE.match(line):
        _, opts_str = _split_pattern_options(line)
        opts = _parse_options(opts_str) if opts_str else RuleOptions()
        csp_val = opts.csp or ""
        return CspRule(raw=raw, csp_value=csp_val, options=opts)

    # --- Element hiding, scriptlets, extended CSS ---
    sep_match = _HIDE_SEP_RE.search(line)
    if sep_match:
        sep = sep_match.group(1)
        domain_part = line[: sep_match.start()]
        body = line[sep_match.end() :]

        includes, excludes = (
            _parse_domain_list(domain_part) if domain_part else ([], [])
        )

        # Scriptlet: ##+js(name, arg1, arg2)
        if sep == "##+js(":
            inner = body.rstrip(")")
            parts = [p.strip() for p in inner.split(",", 1)]
            name = parts[0] if parts else ""
            args_raw = parts[1] if len(parts) > 1 else ""
            # Split args on ", " but not inside $remove$ tokens
            args = [a.strip() for a in re.split(r",\s*", args_raw)] if args_raw else []
            return ScriptletRule(
                raw=raw,
                scriptlet_name=name,
                arguments=args,
                applies_to=includes,
                excludes=excludes,
            )

        # Exception element-hide: #@#
        is_exception = sep == "#@#"
        return ElementHideRule(
            raw=raw,
            is_exception=is_exception,
            selector=body,
            applies_to=includes,
            excludes=excludes,
        )

    # --- Network rules ---
    is_exception = line.startswith("@@")
    if is_exception:
        line = line[2:]

    pattern, opts_str = _split_pattern_options(line)
    opts = _parse_options(opts_str) if opts_str else RuleOptions()

    return NetworkRule(
        raw=raw,
        is_exception=is_exception,
        pattern=pattern,
        is_domain_anchor=pattern.startswith("||"),
        is_start_anchor=pattern.startswith("|") and not pattern.startswith("||"),
        is_end_anchor=pattern.endswith("|"),
        has_separator="^" in pattern,
        has_wildcard="*" in pattern,
        options=opts,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_text(text: str) -> FilterList:
    """Parse a filter list from a string and return a FilterList."""
    metadata: dict[str, str] = {}
    rules: list[AnyRule] = []
    errors: list[tuple[int, str, str]] = []

    # The header region is everything before the first real rule line.
    # The "[Adblock Plus X.Y]" declaration on line 1 is not a comment, so we
    # treat any line matching that pattern as still part of the header.
    _ABPHEADER = re.compile(r"^\[Adblock Plus", re.IGNORECASE)
    in_header = True

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        if in_header and not line.startswith("!") and not _ABPHEADER.match(line):
            in_header = False

        # [Adblock Plus X.Y] declaration — record as metadata and skip
        if _ABPHEADER.match(line):
            metadata["_format"] = line.strip("[]")
            continue

        try:
            rule = _parse_line(line, in_header=in_header)
            if rule is None:
                continue
            if isinstance(rule, MetadataLine):
                metadata[rule.key] = rule.value
            rules.append(rule)
        except Exception as exc:  # noqa: BLE001
            errors.append((lineno, raw_line, str(exc)))

    return FilterList(metadata=metadata, rules=rules, parse_errors=errors)


def parse_file(path: str | Path) -> FilterList:
    """Parse a filter list from a file path and return a FilterList."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_text(text)


def iter_rules(path: str | Path) -> Iterator[AnyRule]:
    """Memory-efficient generator that yields rules one at a time."""
    in_header = True
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n").strip()
            if not line:
                continue
            if in_header and not line.startswith("!"):
                in_header = False
            try:
                rule = _parse_line(line, in_header=in_header)
                if rule is not None:
                    yield rule
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "easyprivacy.txt"
    print(f"Parsing {path} …")
    fl = parse_file(path)

    print("\n── Metadata ──────────────────────────────")
    for k, v in fl.metadata.items():
        print(f"  {k}: {v}")

    print("\n── Summary ───────────────────────────────")
    for k, v in fl.summary().items():
        print(f"  {k:20s} {v:>7,}")

    print("\n── Sample: first 3 block rules ───────────")
    for r in fl.block_rules[:3]:
        print(f"  pattern={r.pattern!r}")
        print(f"    domain_anchor={r.is_domain_anchor}  has_sep={r.has_separator}")
        if r.options.third_party is not None:
            print(f"    third_party={r.options.third_party}")
        if r.options.content_types_include:
            print(f"    types={[ct.value for ct in r.options.content_types_include]}")
        if r.options.domain_includes or r.options.domain_excludes:
            print(f"    domain_includes={r.options.domain_includes}")
            print(f"    domain_excludes={r.options.domain_excludes}")

    print("\n── Sample: first 3 exception rules ───────")
    for r in fl.exception_rules[:3]:
        print(f"  pattern={r.pattern!r}  domain={r.options.domain_includes}")

    print("\n── Sample: scriptlet rules ────────────────")
    for r in fl.scriptlet_rules[:5]:
        print(f"  {r.scriptlet_name}({', '.join(r.arguments)})  → {r.applies_to}")

    print("\n── Sample: CSP rules ──────────────────────")
    for r in fl.csp_rules[:3]:
        print(f"  csp={r.csp_value!r}")
        print(f"    domains={r.options.domain_includes}")

    if fl.parse_errors:
        print(f"\n── Parse errors ({len(fl.parse_errors)}) ──────────────────")
        for lineno, raw, msg in fl.parse_errors[:5]:
            print(f"  line {lineno}: {msg}")
            print(f"    {raw[:80]}")
