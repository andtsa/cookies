#!/bin/bash

# script to (re)run all plots that use cookies_data/ from the main crawl

set -euo pipefail

prog=$(basename "$0")
scripts=${1:-}
data=${2:-}
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

python "$scripts"/compare_tracker_sources.py --data "$data" --out plots
python "$scripts"/plot_cookie_initiators.py --data "$data" --out plots/third_party
python "$scripts"/plot_cookie_reads.py --data "$data" --out plots/cookie_reads
python "$scripts"/plot_cookie_set_by_type.py --data "$data" --out plots/third_party
python "$scripts"/plot_cookie_survival.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_cross_browser.py --data "$data" --out plots/cross_browser
python "$scripts"/plot_ep_effectiveness.py --data "$data" --out plots/trackers
python "$scripts"/plot_lifetime_buckets.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_longterm_offenders.py --data "$data" --out plots/cookie_lifetime --top_n 25
python "$scripts"/plot_scatter.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_security_flags.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_session_vs_persistent_donut.py --data "$data" --out plots/cookie_lifetime
python "$scripts"/plot_third_party_setters.py --data "$data" --out plots/third_party
python "$scripts"/plot_tracker_by_lifetime.py --data "$data" --out plots/trackers
python "$scripts"/plot_tracker_donut.py --data "$data" --out plots/trackers
python "$scripts"/plot_tracker_offenders.py --data "$data" --out plots/trackers --top_n 25
python "$scripts"/plot_trackers_vs_rank.py --data "$data" --rank list_websites_1M.csv --out plots/trackers

echo "done"