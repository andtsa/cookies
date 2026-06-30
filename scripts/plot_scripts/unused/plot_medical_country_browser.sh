#!/bin/bash

# Runs the medical/popular comparison, cross-country comparison, and
# Netherlands browser comparison plot scripts.
#
#   plot_trackers_medical_vs_popular.py  -> full dataset, NL + chromium
#   plot_trackers_across_countries.py    -> Netherlands, CA, SG, US, JP
#   plot_browser_tracker_comparison.py   -> Netherlands only (only country
#                                            with more than one browser)

set -euo pipefail

prog=$(basename "$0")
scripts=${1:-scripts/plot_scripts}
data=${2:-cookies_data}

usage() {
  cat <<EOF
Usage: $prog <scripts dir> <data dir>
EOF
  exit 2
}

if [[ -z "$scripts" || -z "$data" ]]; then
  usage
fi

if [[ ! -d "$scripts" ]]; then
  echo "Error: '$scripts' is not a directory" >&2
  exit 1
fi

if [[ ! -d "$data" ]]; then
  echo "Error: '$data' is not a directory" >&2
  exit 1
fi

# normalize paths
scripts=$(cd "$scripts" && pwd)
data=$(cd "$data" && pwd)

echo "============================================"
echo "MEDICAL / COUNTRY / BROWSER PLOT RUNNER"
echo "============================================"
echo "Scripts dir: $scripts"
echo "Data dir: $data"
echo ""

echo "========== 1. MEDICAL VS POPULAR (NL + chromium, full dataset) =========="
python "$scripts"/plot_trackers_medical_vs_popular.py --data "$data" --out plots/health_vs_all

echo ""
echo "========== 2. CROSS-COUNTRY COMPARISON (Netherlands, CA, SG, US, JP) =========="
python "$scripts"/plot_trackers_across_countries.py --data "$data" \
  --countries Netherlands CA SG US JP \
  --out plots/by_country

echo ""
echo "========== 3. BROWSER COMPARISON (Netherlands only) =========="
python "$scripts"/plot_browser_tracker_comparison.py --data "$data" \
  --country Netherlands --out plots/browser_comparison

echo ""
echo "============================================"
echo "✓ ALL PLOTS COMPLETED"
echo "============================================"
