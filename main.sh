#!/bin/sh

./.venv/bin/python3 -m crawler \
    --batch-size 30 \
    --failed-sites="cookies_data/failed_sites.csv" \
    --timeout-ms=30000 \
    -O \
    -c 20 \
    --category="popular" --country="Netherlands" -i ./list_websites_1M.csv

    # -c 12 --force-concurrency \
