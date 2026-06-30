# Cookie Tracking Analysis on Sensitive Websites

This repository contains the crawler, analysis package, and plot scripts for our study of third-party cookie tracking across health and non-health websites.

We investigate:
- How many and which third-party trackers are present on health websites versus popular websites
- Whether tracking behaviour differs across countries and browsers
- How trackers are identified through multiple signals: filter lists, cross-site cookie sharing, cookie syncing, and cross-domain JavaScript reads

## Repository structure

```
.
├── crawler/          # Playwright-based browser crawler (python -m crawler)
├── client/           # Browser client and tracker-list helpers used by the crawler
├── classifier/       # Sensitive-website text classifier (health vs. general)
├── analysis/         # CookieDataset: the single analysis entrypoint for crawl data
│   ├── src/          # Internal implementation (loading, EP matching, sharing, syncing)
│   └── access/       # Mixin layers: raw access, frame building, aggregation, relational
├── scripts/
│   ├── annotate.py              # Pre-warm the analysis cache (run once after crawling)
│   ├── cross_reference_sync_reads.py  # Join syncing events with JS read traces
│   ├── dump_tracker_pathways_table.py # Table of party × setter × channel routes
│   └── plot_scripts/
│       ├── publish/             # Final figures used in the paper
│       └── utils.py             # Shared plot helpers (dataset loader, colour palette)
├── tests/            # Unit tests (matcher parity, entropy, name similarity, syncing)
└── requirements.txt
```

## Setup

**1. Create and activate a virtual environment**

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

**2. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**3. Install Playwright browsers**

```bash
python -m playwright install chromium firefox webkit
```

The `hyperscan` package (listed in `requirements.txt`) is optional and Linux/x86\_64-only. The matcher falls back to the stdlib `re` engine automatically when it is not available. The results are identical, but annotation is much slower on large crawls.

## Reproducing the study

### Obtain the website lists

The Tranco Top-1M list used for the popular-website crawl must be downloaded from [https://tranco-list.eu/](https://tranco-list.eu/) and saved as `list_websites_1M.csv` in the project root (format: `rank,domain` CSV).

The health-website list (`list_websites_health.csv`) is included in this repository.

### Crawl websites

The crawler collects cookies, outgoing requests, and JavaScript `document.cookie` reads for each site and writes one JSON file per site under `cookies_data/{country}/{browser}/{prefix}/{domain}.json`.

**Basic usage: single country, single browser:**

```bash
python -m crawler \
    --browsers chromium \
    --country "Netherlands" \
    --category popular \
    --tracker-lists \
    --cookie-reads \
    -i list_websites_1M.csv
```

**Crawl with multiple browsers (Netherlands, our main dataset):**

```bash
python -m crawler \
    --browsers chromium chrome firefox edge brave \
    --country "Netherlands" \
    --category popular \
    --tracker-lists \
    --cookie-reads \
    -i list_websites_1M.csv
```

**Health-website crawl:**

```bash
python -m crawler \
    --browsers chromium \
    --country "Netherlands" \
    --category health \
    --tracker-lists \
    --cookie-reads \
    -i list_websites_health.csv
```

**flags:**

| Flag | Default | Description |
|---|---|---|
| `--browsers` | `chromium` | One or more of: `chromium`, `chrome`, `firefox`, `edge`, `brave`, `webkit` |
| `--country` | `Netherlands` | Label stored in each output file's `crawl_context` |
| `--category` | `popular` | Label stored in each output file's `crawl_context` |
| `--limit N` | none | Stop after N sites (useful for testing) |
| `--concurrency N` | auto | Parallel browser slots; auto-tuned to CPU/RAM if omitted |
| `--timeout-ms` | `10000` | Page load timeout |
| `--overwrite` | off | Re-crawl sites that already have output files |
| `--tracker-lists` | on | Annotate cookies with EasyPrivacy / OpenCookieDB membership |
| `--cookie-reads` | on | Intercept and record JS `document.cookie` reads |

The crawler resumes automatically from a `progress.txt` checkpoint if interrupted. Use `--skip-first N` to override the resume point.

**Cross-country crawls** (CA, SG, US, JP in our study) require a VPN routed through the target country. Connect the VPN, then run the crawler with `--country CA` (or the appropriate country code) using the same command as above.

### Pre-warm the annotation cache

Running the analysis cold re-annotates every site on each invocation. Pre-warm the cache once after crawling so that plot scripts load from disk:

```bash
python scripts/annotate.py \
    --data cookies_data \
    --cache-dir .analysis_cache \
    --workers 8
```

This builds the enriched cookie/site DataFrames, EasyPrivacy match verdicts, and the three relational artefacts (shared groups, sync events, cross-domain reads) and persists them to `.analysis_cache/`. Subsequent runs load from cache and complete in seconds.

### Generate plots

Each script under `scripts/plot_scripts/publish/` produces the figures used in the paper. Run them individually from the project root:

```bash
python scripts/plot_scripts/publish/plot_trackers_medical_vs_popular.py
python scripts/plot_scripts/publish/plot_evidence_sources.py
python scripts/plot_scripts/publish/plot_tracker_venn.py
python scripts/plot_scripts/publish/plot_upset_signals.py
python scripts/plot_scripts/publish/plot_trackers_across_countries.py
python scripts/plot_scripts/publish/plot_browser_tracker_comparison.py
python scripts/plot_scripts/publish/plot_tracker_count_vs_rank.py
# ... etc.
```

## Data format

Each crawled site is stored as a single JSON file at:

```
cookies_data/{country}/{browser}/{2-char hex prefix}/{domain}.json
```

Top-level keys:

| Key | Description |
|---|---|
| `target_url` | URL visited by the crawler |
| `crawl_context` | `{rank, category, country, browser}` decoded from the input CSV and VPN config |
| `cookies` | List of cookie objects (name, value, domain, path, expiry, `is_tracker`, `tracker_lists`, ...) |
| `requests` | List of outgoing request URLs (Chromium only; used for EasyPrivacy matching and syncing detection) |
| `js_activity` | Recorded `document.cookie` reads with JS call-stack traces |
| `error` | Present when the page failed to load |

The `requests` field retains full URLs including query strings as required for cookie-syncing detection. Treat these as observational web-measurement data.

## the analysis package

The `analysis.CookieDataset` class is the single entrypoint for loading and querying crawl data:

```python
from analysis import CookieDataset

ds = CookieDataset("cookies_data", cache_dir=".analysis_cache")

ds.cookies                    # per-cookie DataFrame (list-based tracker annotation)
ds.classified_cookies         # + tiered classifier labels (confirmed/probable/etc.)
ds.sites                      # per-site DataFrame

ds.group(by=["country"], metric="mean:is_tracker_listed")
ds.filter(country="Netherlands", browser="chromium")
ds.shared()                   # shared-cookie groups
ds.syncing()                  # cookie-syncing events
ds.cross_domain_reads()       # cross-domain JS read events
```

this allows us to store meta-fields such as tracker detection in a cache that is (partially) invalidated when new crawl data is added,
or when the analysis pipeline is changed. this is what makes it feasible to keep consistency across all plots and analyses, and to efficiently generate plots with >150gb of data.

## Ethical considerations

This study collects only publicly observable browser cookie metadata from automated, unauthenticated visits. It does not bypass authentication, access user accounts, scrape personal data, or circumvent security protections. The study was conducted for privacy research purposes.

## Citation

If you use this code or dataset in your research, please cite:

```
[citation to be added]
```

## Authors

Andreas Tsatsanis, Stefan Minkov, Galya Vergieva, Aleksandra Savova, Denisa Arsene, Alexia Neatu

## License

[Apache 2.0](LICENSE).
