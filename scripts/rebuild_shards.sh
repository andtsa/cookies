#!/usr/bin/env bash
# rebuild_shards.sh — rebuild the annotation cache for every {country}/{browser}
# shard, matching _discover_shards' "*/*" layout and the plot loader's cache dir.
set -uo pipefail

DATA="${1:-./cookies_data}"          # crawl root (contains {country}/{browser}/...)
CACHE_DIR="${CACHE_DIR:-.analysis_cache}"
WORKERS="${WORKERS:-$(( $(nproc) - 1 ))}"
ENGINE="${ENGINE:-hyperscan}"
RANK_CAP="${RANK_CAP:-100000}"

# Activate the conda env (adjust if your shell already has it active).
source activate hl 2>/dev/null || conda activate hl 2>/dev/null || true

# Discover {country}/{browser} shards exactly as _discover_shards does (depth 2).
mapfile -t SHARDS < <(find "$DATA" -mindepth 2 -maxdepth 2 -type d | sort)

if [ "${#SHARDS[@]}" -eq 0 ]; then
  echo "No {country}/{browser} shards found under '$DATA'" >&2
  exit 1
fi

echo "Found ${#SHARDS[@]} shards under '$DATA'"
failed=()
i=0
for shard in "${SHARDS[@]}"; do
  i=$((i+1))
  echo "==================================================================="
  echo "[$i/${#SHARDS[@]}] rebuilding: $shard"
  echo "==================================================================="
  if python scripts/annotate.py \
        --data "$shard" \
        --cache-dir "$CACHE_DIR" \
        --workers "$WORKERS" \
        --engine "$ENGINE" \
        --rank-cap "$RANK_CAP" \
        --rebuild; then
    echo "OK: $shard"
  else
    echo "FAILED: $shard" >&2
    failed+=("$shard")
  fi
done

echo "==================================================================="
echo "Done. ${#SHARDS[@]} shards, ${#failed[@]} failed."
if [ "${#failed[@]}" -gt 0 ]; then
  printf '  FAILED: %s\n' "${failed[@]}" >&2
  exit 1
fi
