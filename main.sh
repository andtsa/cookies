#!/bin/sh

./.venv/bin/python3 -m crawler \
    --batch-size 30 \
    --failed-sites="cookies_data/failed_sites.csv" \
    --timeout-ms=10000 \
    -O \
    --category="popular" --country="Netherlands" -i ./list_websites_1M.csv

    # -c 12 --force-concurrency \
