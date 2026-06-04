#!/bin/sh

./.venv/bin/python3 scripts/get_cookies.py \
    -c 30 --batch-size 30 --force-concurrency \
    --failed-sites="cookies_data/failed_sites.csv" \
    --category="popular" --country="Netherlands" -i ./list_websites_1M.csv
