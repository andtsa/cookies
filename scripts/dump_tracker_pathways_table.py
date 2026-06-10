"""
Dump a summary table of tracker delivery pathways for a given crawl.

Prints a cross-tabulation of:

    Party context  ×  Setter mechanism  ×  Delivery channel

showing, for every combination observed in the data:

    count       — total cookies on that route
    trackers    — how many are flagged by a tracker list
    trk %       — tracker share of that route (trackers / count × 100)
    % all       — share of all cookies in the crawl (count / total × 100)

Sorted by count descending so the most common routes are at the top.

Usage:
    python scripts/dump_tracker_pathways_table.py
    python scripts/dump_tracker_pathways_table.py --country Netherlands --browser chromium
    python scripts/dump_tracker_pathways_table.py --data cookies_data --out pathways.csv
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "plot_scripts"))
from utils import dataset

_CHANNEL_BY_REQUEST_TYPE = {
    "Document": "Page load",
    "Image": "Tracking pixel",
    "Script": "Script tag",
    "Fetch": "Background call",
    "XHR": "Background call",
    "Ping": "Beacon",
    "SubDocument": "Iframe",
}

PARTY_LABELS = {
    "first_party": "First-party",
    "third_party": "Third-party",
    "unknown": "Unknown",
}

MECHANISM_LABELS = {
    "http": "HTTP (Set-Cookie)",
    "javascript": "JavaScript write",
    "unknown": "Unknown mechanism",
}


def _channel(setter_type: str, request_type) -> str:
    if setter_type == "http":
        return _CHANNEL_BY_REQUEST_TYPE.get(
            request_type, f"Other HTTP ({request_type or 'None'})"
        )
    if setter_type == "javascript":
        return "JS write"
    return "Unknown"


def _provider_from_cookie(c: dict, registered_domain_fn) -> str:
    """Derive the tracker provider from the cookie's setter URL.

    Priority:
      1. Registered domain of ``setter_url``     (HTTP-set cookies)
      2. Registered domain of ``setter_frame_url`` (JS-set cookies)
      3. Registered domain of the cookie's own ``domain``

    This gives the actual company setting the tracker (e.g. ``google.com``,
    ``facebook.net``) rather than the ``tracker_provider`` field, which is
    only populated for EasyPrivacy domain-rule matches and is null for the
    majority of OCDB-detected cookies.
    """
    for url_field in ("setter_url", "setter_frame_url"):
        url = c.get(url_field)
        if url:
            rd = registered_domain_fn(url)
            if rd:
                return rd
    # Fall back to the cookie's own domain (always present)
    return registered_domain_fn(c.get("domain", "")) or "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data")
    parser.add_argument("--country", default="Netherlands")
    parser.add_argument("--browser", default="chromium")
    parser.add_argument("--out", default=None, help="Optional path to save as CSV")
    args = parser.parse_args()

    from analysis.src.helpers import registered_domain

    ds = dataset(args.data)

    from collections import Counter

    # classified_cookies carries the canonical is_tracker (tracker_tier >= "probable"),
    # which is what we want for the tracker-share column in this table.
    df = ds.classified_cookies
    df = df[(df["country"] == args.country) & (df["browser"] == args.browser)]

    # Collect (party, mechanism, channel) -> [total, tracker_count]
    counts: dict[tuple, list] = defaultdict(lambda: [0, 0])
    # (party, mechanism, channel) -> Counter of tracker_provider
    providers: dict[tuple, Counter] = defaultdict(Counter)

    for row in df.itertuples(index=False):
        party = PARTY_LABELS.get(row.party_type, "Unknown")
        setter_type = row.set_by_type or "unknown"
        mechanism = MECHANISM_LABELS.get(setter_type, setter_type)
        channel = _channel(setter_type, row.setter_request_type)
        is_trk = bool(row.is_tracker)
        key = (party, mechanism, channel)
        counts[key][0] += 1
        counts[key][1] += int(is_trk)
        if is_trk:
            # Prefer registered domain of setter_url, fall back to
            # setter_frame_url, then cookie_domain.
            prov = "unknown"
            for url in (row.setter_url, row.setter_frame_url):
                if url and isinstance(url, str):
                    rd = registered_domain(url)
                    if rd:
                        prov = rd
                        break
            if prov == "unknown" and row.cookie_domain:
                prov = registered_domain(str(row.cookie_domain)) or "unknown"
            providers[key][prov] += 1

    if not counts:
        print(f"No cookies found for {args.country}/{args.browser} in {args.data!r}.")
        return

    total = sum(v[0] for v in counts.values())
    rows = sorted(
        [(k, v) for k, v in counts.items()],
        key=lambda x: x[1][0],
        reverse=True,
    )

    # Column widths
    c_party = max(len("Party context"), max(len(k[0]) for k, _ in rows))
    c_mech = max(len("Setter mechanism"), max(len(k[1]) for k, _ in rows))
    c_channel = max(len("Delivery channel"), max(len(k[2]) for k, _ in rows))
    c_count = max(len("count"), len(f"{total:,}"))
    c_trk = max(len("trackers"), len(f"{max(v[1] for _, v in rows):,}"))
    c_tpct = len("trk %")
    c_apct = len("% all")

    # Format top-N providers per route as a compact string, e.g.:
    #   "mc.yandex.com×12, demdex.net×8, (+3 more)"
    TOP_N = 3

    def _fmt_providers(key, trk_count):
        if trk_count == 0:
            return ""
        ctr = providers[key]
        top = ctr.most_common(TOP_N)
        parts = [f"{p}×{n}" for p, n in top]
        rest = len(ctr) - len(top)
        if rest > 0:
            parts.append(f"(+{rest} more)")
        return ", ".join(parts)

    c_prov = max(
        len("top tracker providers"),
        max(len(_fmt_providers(k, v[1])) for k, v in rows) or 0,
    )

    sep = (
        f"+{'-'*(c_party+2)}+{'-'*(c_mech+2)}+{'-'*(c_channel+2)}"
        f"+{'-'*(c_count+2)}+{'-'*(c_trk+2)}+{'-'*(c_tpct+2)}+{'-'*(c_apct+2)}"
        f"+{'-'*(c_prov+2)}+"
    )
    header = (
        f"| {'Party context':<{c_party}} | {'Setter mechanism':<{c_mech}} "
        f"| {'Delivery channel':<{c_channel}} | {'count':>{c_count}} "
        f"| {'trackers':>{c_trk}} | {'trk %':>{c_tpct}} | {'% all':>{c_apct}} "
        f"| {'top tracker providers':<{c_prov}} |"
    )

    print(
        f"\nTracker delivery pathways — {args.country} / {args.browser}  ({total:,} cookies total)\n"
    )
    print(sep)
    print(header)
    print(sep)
    for key, (cnt, trk) in rows:
        party, mech, channel = key
        trk_pct = trk / cnt * 100 if cnt else 0.0
        all_pct = cnt / total * 100
        prov_str = _fmt_providers(key, trk)
        print(
            f"| {party:<{c_party}} | {mech:<{c_mech}} | {channel:<{c_channel}} "
            f"| {cnt:>{c_count},} | {trk:>{c_trk},} | {trk_pct:>{c_tpct}.1f} | {all_pct:>{c_apct}.1f} "
            f"| {prov_str:<{c_prov}} |"
        )
    print(sep)
    print(f"  {'TOTAL':<{c_party+c_mech+c_channel+8}} {total:>{c_count},}")
    print()

    # --- Per-provider summary across all routes ---
    all_providers: Counter = Counter()
    for ctr in providers.values():
        all_providers.update(ctr)

    if all_providers:
        print(
            f"Provider summary ({len(all_providers)} distinct providers across all tracker cookies):\n"
        )
        c_pn = max(len("provider"), max(len(p) for p in all_providers))
        c_pc = max(len("cookies"), len(f"{all_providers.most_common(1)[0][1]:,}"))
        psep = f"+{'-'*(c_pn+2)}+{'-'*(c_pc+2)}+{'-'*7}+"
        print(psep)
        print(f"| {'provider':<{c_pn}} | {'cookies':>{c_pc}} | {'% trk':>5} |")
        print(psep)
        total_trk = sum(v[1] for v in counts.values())
        for prov, n in all_providers.most_common():
            if n < 10:
                continue
            pct = n / total_trk * 100 if total_trk else 0.0
            print(f"| {prov:<{c_pn}} | {n:>{c_pc},} | {pct:>5.1f} |")
        print(psep)
        print()

    # Optionally save as CSV
    if args.out:
        import csv

        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "party_context",
                    "setter_mechanism",
                    "delivery_channel",
                    "count",
                    "trackers",
                    "trk_pct",
                    "pct_all",
                    "top_providers",
                ]
            )
            for key, (cnt, trk) in rows:
                party, mech, channel = key
                w.writerow(
                    [
                        party,
                        mech,
                        channel,
                        cnt,
                        trk,
                        round(trk / cnt * 100, 1) if cnt else 0.0,
                        round(cnt / total * 100, 1),
                        _fmt_providers(key, trk),
                    ]
                )
        print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
