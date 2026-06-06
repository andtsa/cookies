from __future__ import annotations

import argparse
import json
from collections import defaultdict

import tldextract


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def etld1(domain: str) -> str:
    """
    Convert:
        www.google.com -> google.com
        sub.example.co.uk -> example.co.uk
    """
    if not domain:
        return ""

    ext = tldextract.extract(domain)

    return ".".join(
        p
        for p in [ext.domain, ext.suffix]
        if p
    )


def build_read_index(reads_file: str) -> dict[str, list[dict]]:
    """
    Build:

        cookie_name -> [
            {
                reader_domain,
                reader_script,
                visited_domain
            }
        ]
    """

    with open(reads_file, encoding="utf-8") as f:
        reads = json.load(f)

    index = defaultdict(list)

    for cookie_name, entries in reads.items():

        for entry in entries:

            index[cookie_name].append(
                {
                    "reader_domain": entry.get("reader_domain"),
                    "reader_script": entry.get("reader_script"),
                    "visited_domain": entry.get("visited_domain"),
                }
            )

    return dict(index)


def sync_parties(site_domain: str, sync_entry: dict) -> set[str]:
    """
    Returns all domains directly involved in a sync.

    Example:

        site_domain = yandex.net
        to_domain   = ya.ru

    Returns:

        {
            "yandex.net",
            "ya.ru"
        }
    """

    parties = set()

    if site_domain:
        parties.add(etld1(site_domain))

    to_domain = sync_entry.get("to_domain")

    if to_domain:
        parties.add(etld1(to_domain))

    return parties


# ---------------------------------------------------------
# Main analysis
# ---------------------------------------------------------

def enrich_sync_data(
    sync_file: str,
    reads_file: str,
):
    """
    Produces:

        enriched_data
        external_readers
    """

    read_index = build_read_index(reads_file)

    with open(sync_file, encoding="utf-8") as f:
        sync_data = json.load(f)

    enriched = []
    external_readers = []

    for site_entry in sync_data:

        syncing = site_entry.get("cookie_syncing", {})

        site_domain = syncing.get("site_domain")

        for bucket in ["confirmed", "candidates"]:

            for sync_entry in syncing.get(bucket, []):

                cookie_name = sync_entry.get("cookie_name")

                if not cookie_name:
                    continue

                readers = read_index.get(cookie_name, [])

                sync_entry["readers"] = readers

                involved_parties = sync_parties(
                    site_domain,
                    sync_entry,
                )

                for reader in readers:

                    reader_domain = reader.get(
                        "reader_domain"
                    )

                    if not reader_domain:
                        continue

                    reader_etld = etld1(
                        reader_domain
                    )

                    if reader_etld not in involved_parties:

                        external_readers.append(
                            {
                                "site_domain": site_domain,
                                "cookie_name": cookie_name,
                                "sync_to": sync_entry.get(
                                    "to_domain"
                                ),
                                "reader_domain": reader_domain,
                                "reader_script": reader.get(
                                    "reader_script"
                                ),
                                "visited_domain": reader.get(
                                    "visited_domain"
                                ),
                            }
                        )

        enriched.append(site_entry)

    return enriched, external_readers


# ---------------------------------------------------------
# CLI
# ---------------------------------------------------------

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Cross-reference cookie syncing with cookie readers."
        )
    )

    parser.add_argument(
        "sync_file",
        help="cookie syncing JSON"
    )

    parser.add_argument(
        "reads_file",
        help="reads_filtered.json"
    )

    parser.add_argument(
        "--out-prefix",
        default="sync_reads",
        help="Output file prefix"
    )

    return parser.parse_args()


def main():

    args = parse_args()

    print("Loading data...")

    enriched, external = enrich_sync_data(
        args.sync_file,
        args.reads_file,
    )

    enriched_path = (
        f"{args.out_prefix}_enriched.json"
    )

    external_path = (
        f"{args.out_prefix}_external_readers.json"
    )

    with open(
        enriched_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            enriched,
            f,
            indent=2,
        )

    with open(
        external_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            external,
            f,
            indent=2,
        )

    print()
    print(
        f"Enriched sync data written to: "
        f"{enriched_path}"
    )

    print(
        f"External readers written to: "
        f"{external_path}"
    )

    print(
        f"External reader records: "
        f"{len(external):,}"
    )


if __name__ == "__main__":
    main()