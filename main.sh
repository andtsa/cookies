#!/bin/sh

./.venv/bin/python3 -m crawler \
    --batch-size 30 \
    --failed-sites="cookies_data/failed_sites.csv" \
    --category="popular" --country="Netherlands" -i ./list_websites_1M.csv
    --timeout-ms=5000

    # -c 12 --force-concurrency \
