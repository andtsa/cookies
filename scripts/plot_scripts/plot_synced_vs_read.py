"""
scripts/sync_vs_reads_table.py

Compare:

Domain / Organization
    -> number of confirmed syncs
    -> number of cookie reads

Output:
    sync_vs_reads.csv
"""

import json
import pandas as pd
from collections import defaultdict


# --------------------------------------------------
# INPUT FILES
# --------------------------------------------------

READS_FILE = "reads_filtered.json"
SYNC_FILE = "sync_analysis_enriched.json"

OUTPUT_CSV = "sync_vs_reads.csv"


# --------------------------------------------------
# NORMALIZATION
# --------------------------------------------------

DOMAIN_MAP = {
    # Google
    "google.com": "Google",
    "google-analytics.com": "Google",
    "googletagmanager.com": "Google",
    "googlesyndication.com": "Google",
    "googleadservices.com": "Google",
    "doubleclick.net": "Google",
    "gstatic.com": "Google",

    # Yandex
    "yandex.ru": "Yandex",
    "yandex.com": "Yandex",
    "ya.ru": "Yandex",
    "yastatic.net": "Yandex",

    # Microsoft
    "clarity.ms": "Microsoft",
    "bing.com": "Microsoft",
    "microsoft.com": "Microsoft",

    # Meta
    "facebook.com": "Meta",
    "facebook.net": "Meta",
    "fbcdn.net": "Meta",

    # Amazon
    "amazon.com": "Amazon",
    "amazon-adsystem.com": "Amazon",
}


def normalize(domain):

    if not domain:
        return None

    domain = domain.lower()

    for suffix, label in DOMAIN_MAP.items():
        if domain.endswith(suffix):
            return label

    return domain


# --------------------------------------------------
# READS
# --------------------------------------------------

print("Loading reads...")

with open(READS_FILE, encoding="utf-8") as f:
    reads_data = json.load(f)

reads_count = defaultdict(int)

for cookie_name, entries in reads_data.items():

    for entry in entries:

        reader = normalize(
            entry.get("reader_domain")
        )

        if not reader:
            continue

        reads_count[reader] += 1


# --------------------------------------------------
# SYNCS
# --------------------------------------------------

print("Loading syncs...")

with open(SYNC_FILE, encoding="utf-8") as f:
    sync_data = json.load(f)

sync_count = defaultdict(int)

for site in sync_data:

    syncing = site.get("cookie_syncing", {})

    for item in syncing.get("confirmed", []):

        target = normalize(
            item.get("to_domain")
        )

        if not target:
            continue

        sync_count[target] += 1


# --------------------------------------------------
# MERGE
# --------------------------------------------------

all_domains = (
    set(reads_count.keys())
    | set(sync_count.keys())
)

rows = []

for domain in all_domains:

    reads = reads_count.get(domain, 0)
    syncs = sync_count.get(domain, 0)

    rows.append(
        {
            "Domain": domain,
            "Syncs": syncs,
            "Reads": reads,
            "Total": syncs + reads,
        }
    )

df = pd.DataFrame(rows)

df = df.sort_values(
    "Total",
    ascending=False,
)

# --------------------------------------------------
# OUTPUT
# --------------------------------------------------

print()
print(df.head(50).to_string(index=False))

df.to_csv(
    OUTPUT_CSV,
    index=False,
)

print(f"\nSaved -> {OUTPUT_CSV}")