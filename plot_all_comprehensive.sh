#!/bin/bash

# Comprehensive script to run ALL plot scripts with all available country/browser combinations
#
# Target data structure:
#   Countries: Netherlands, CA, SG, US, JP
#   Browsers for Netherlands: chromium, chrome, firefox, edge, brave (5 browsers)
#   Browsers for others (CA, SG, US, JP): chromium only
#
# Strategy:
#   1. Country/browser-unrelated scripts: use Netherlands + chromium (defaults)
#   2. Country-specific scripts: iterate over all countries with chromium
#   3. Country+Browser scripts: iterate all combinations
#   4. Browser comparison scripts: use all data at once

set -euo pipefail

prog=$(basename "$0")
scripts=${1:-scripts/plot_scripts}
data=${2:-cookies_data}
cmd=${3:-info}

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
echo "COMPREHENSIVE PLOT SCRIPT RUNNER"
echo "============================================"
echo "Scripts dir: $scripts"
echo "Data dir: $data"
echo ""

# Define available countries and browsers
COUNTRIES=("Netherlands" "CA" "SG" "US" "JP")
BROWSERS_NL=("chromium" "chrome" "firefox" "edge" "brave")
BROWSERS_OTHER=("chromium")

# Helper function to get browsers for a country
get_browsers() {
  local country=$1
  case "$country" in
    Netherlands) printf '%s\n' "${BROWSERS_NL[@]}" ;;
    CA|SG|US|JP) printf '%s\n' "${BROWSERS_OTHER[@]}" ;;
    *) echo "chromium" ;;
  esac
}

echo "========== 1. COUNTRY/BROWSER-UNRELATED SCRIPTS (NL + chromium) =========="
python "$scripts"/compare_tracker_sources.py --data "$data" --out plots
python "$scripts"/plot_cookie_initiators.py --data "$data" --out plots/third_party
python "$scripts"/plot_cookie_reads.py --data "$data" --out plots/cookie_reads
python "$scripts"/plot_cookie_set_by_type.py --data "$data" --out plots/third_party
python "$scripts"/plot_cookie_set_by_types.py --data "$data" --out plots/third_party
python "$scripts"/plot_cookie_survival.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_ep_effectiveness.py --data "$data" --out plots/trackers
python "$scripts"/plot_lifetime_buckets.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_lifetime_survival.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_longterm_offenders.py --data "$data" --out plots/cookie_lifetime --top_n 25
python "$scripts"/plot_scatter.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_security_flags.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_session_vs_persistent_donut.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_third_party_setters.py --data "$data" --out plots/third_party
python "$scripts"/plot_first_vs_third_party.py --data "$data" --out plots/third_party
python "$scripts"/plot_tracker_by_lifetime.py --data "$data" --out plots/trackers
python "$scripts"/plot_tracker_donut.py --data "$data" --out plots/trackers
python "$scripts"/plot_tracker_offenders.py --data "$data" --out plots/trackers --top_n 25
python "$scripts"/plot_trackers_vs_rank.py --data "$data" --out plots/trackers
python "$scripts"/plot_tld_trackers.py

# cross-site identifier sharing + evidence funnel
python "$scripts"/plot_shared_cookies.py --data "$data" --out plots/shared
python "$scripts"/plot_evidence_funnel.py --data "$data" --out plots/funnel

# cookie syncing (engine-computed; cached by annotate.py)
python "$scripts"/plot_cookie_syncing.py --data "$data" --out plots/syncing
python "$scripts"/plot_sync_subtypes_bar.py --data "$data" --out plots/syncing --by tier
python "$scripts"/plot_sync_heatmap.py --data "$data" --out plots/syncing --cols carrier
python "$scripts"/plot_sync_sankey.py --data "$data" --out plots/syncing
python "$scripts"/plot_read_sankey.py --data "$data" --out plots/reads --top 12

# third-party cookie reading
python "$scripts"/plot_third_party_cookie_readers.py --data "$data" --out plots/reads
python "$scripts"/plot_third_party_readers_by_organisations.py --data "$data" --out plots/reads
python "$scripts"/plot_synced_vs_read.py --data "$data" --out plots/reads

echo ""
echo "========== 2. BROWSER COMPARISON (all browsers, Netherlands) =========="
python "$scripts"/plot_cross_browser.py --data "$data" --out plots/cross_browser

echo ""
echo "========== 3. COUNTRY-SPECIFIC SCRIPTS (all countries + chromium) =========="
for country in "${COUNTRIES[@]}"; do
  echo "  → $country + chromium"
  python "$scripts"/plot_browser_tracker_comparison.py --data "$data" --country "$country" --out plots/browser_comparison
done

echo ""
echo "========== 4. COUNTRY+BROWSER COMBINATION SCRIPTS =========="
echo "  → Running all 9 combinations (NL×5 browsers + CA,SG,US,JP×chromium)"
for country in "${COUNTRIES[@]}"; do
  browsers=$(get_browsers "$country")
  # Skip countries with no browser data
  if [[ -z "$browsers" ]]; then
    echo "  ⊘ Skipping $country (no browser data)"
    continue
  fi

  for browser in $browsers; do
    echo "  → $country + $browser"
    python "$scripts"/plot_tracker_heatmap.py --data "$data" --country "$country" --browser "$browser" --out plots/heatmap
    python "$scripts"/plot_tracker_pathways_sankey.py --data "$data" --country "$country" --browser "$browser" --out plots/pathways
    python "$scripts"/plot_tracker_pathways_bars.py --data "$data" --country "$country" --browser "$browser" --out plots/pathways
    python "$scripts"/plot_tracker_pathways_sunburst.py --data "$data" --country "$country" --browser "$browser" --out plots/pathways
    python "$scripts"/plot_tracker_ecosystem_bridge.py --data "$data" --country "$country" --browser "$browser" --out plots/tracker_bridge
  done
done

echo ""
echo "========== 5. SPECIALIZED SCRIPTS =========="
# Medical/health-specific (requires health domains CSV if available)
if [[ -f "health_websites_1K.csv" ]]; then
  echo "  → Medical tracker scripts (health_websites_1K.csv found)"
  python "$scripts"/plot_top_trackers_medical.py
  python "$scripts"/plot_trackers_medical_vs_popular.py
  python "$scripts"/plot_tracker_ecosystem_bridge.py --data "$data" --health health_websites_1K.csv --country Netherlands --browser chromium --out plots/tracker_bridge
else
  echo "  ⊘ Medical scripts skipped (health_websites_1K.csv not found)"
fi

# Rank correlation (uses embedded rank if available)
python "$scripts"/plot_tracker_count_vs_rank.py --data "$data" --out plots/trackers

echo ""
echo "============================================"
echo "✓ ALL PLOTS COMPLETED"
echo "============================================"
