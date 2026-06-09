#!/bin/sh

./.venv/bin/python3 -m crawler \
    --batch-size 30 \
    --timeout-ms=30000 \
    -O \
    -c 20 \
    --limit 111111 \
    --browsers "firefox"
    --category="popular" --country="Netherlands" -i ./list_websites_1M.csv

