"""
Syncs vs Reads per Domain / Organization

For each receiving/reader domain (rolled up to its parent organization where
known), compares two cross-site signals side by side:

    * Syncs — confirmed cookie-sync events received by the domain
              (cookie value arrived as a request parameter), and
    * Reads — third-party JS cookie reads attributed to the domain.

Both are computed by the analysis engine and cached by scripts/annotate.py
(:meth:`CookieDataset.syncing` and :meth:`CookieDataset.third_party_reads`); no
hand-maintained input files. Writes ``sync_vs_reads.csv`` into ``--out`` and a
grouped horizontal bar chart of the top domains by combined volume.

Usage:
    python scripts/plot_scripts/plot_synced_vs_read.py --data cookies_data --out plots/reads --top_n 25
"""

import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    dataset,
    save_figure,
    make_parser,
    clean_ax,
    ACCENT,
    ACCENT2,
    DARK,
    BG,
)

# Domain -> parent organization (suffix match against the registered domain).
DOMAIN_MAP = {
    "google.com": "Google",
    "google-analytics.com": "Google",
    "googletagmanager.com": "Google",
    "googlesyndication.com": "Google",
    "googleadservices.com": "Google",
    "doubleclick.net": "Google",
    "gstatic.com": "Google",
    "yandex.ru": "Yandex",
    "yandex.com": "Yandex",
    "ya.ru": "Yandex",
    "yastatic.net": "Yandex",
    "clarity.ms": "Microsoft",
    "bing.com": "Microsoft",
    "microsoft.com": "Microsoft",
    "facebook.com": "Meta",
    "facebook.net": "Meta",
    "fbcdn.net": "Meta",
    "amazon.com": "Amazon",
    "amazon-adsystem.com": "Amazon",
}


def normalize(domain: str | None) -> str | None:
    if not domain:
        return None
    domain = domain.lower()
    for suffix, label in DOMAIN_MAP.items():
        if domain.endswith(suffix):
            return label
    return domain


def build_table(data_dir: str) -> pd.DataFrame:
    ds = dataset(data_dir)

    sync_count: dict[str, int] = defaultdict(int)
    for event in ds.syncing():
        for ev in event.get("confirmed", []):
            target = normalize(ev.get("to_domain"))
            if target:
                sync_count[target] += 1

    reads_count: dict[str, int] = defaultdict(int)
    for row in ds.third_party_reads():
        reader = normalize(row.get("reader_domain"))
        if reader:
            reads_count[reader] += 1

    domains = set(sync_count) | set(reads_count)
    rows = [
        {
            "Domain": d,
            "Syncs": sync_count.get(d, 0),
            "Reads": reads_count.get(d, 0),
            "Total": sync_count.get(d, 0) + reads_count.get(d, 0),
        }
        for d in domains
    ]
    df = pd.DataFrame(rows).sort_values("Total", ascending=False).reset_index(drop=True)
    return df


def plot_synced_vs_read(data_dir: str, out_dir: str, top_n: int = 25) -> None:
    apply_theme()
    df = build_table(data_dir)

    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "sync_vs_reads.csv")
    df.to_csv(csv_path, index=False)
    print(f"Saved -> {csv_path}")
    if not df.empty:
        print(df.head(50).to_string(index=False))

    fig, ax = plt.subplots(figsize=(11, 8))
    if df.empty:
        ax.text(
            0.5,
            0.5,
            "No sync or read events found",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=14,
            color=DARK,
        )
        ax.axis("off")
        save_figure(out_dir, "sync_vs_reads.png", "sync_vs_reads.pdf")
        return

    top = df.head(top_n).iloc[::-1]  # largest on top after barh
    y = np.arange(len(top))
    h = 0.4
    ax.barh(
        y + h / 2, top["Syncs"], height=h, color=ACCENT, edgecolor=BG, label="Syncs"
    )
    ax.barh(
        y - h / 2, top["Reads"], height=h, color=ACCENT2, edgecolor=BG, label="Reads"
    )
    ax.set_yticks(y)
    ax.set_yticklabels(top["Domain"])
    ax.set_xlabel("Events")
    ax.set_title(f"Syncs vs Reads — top {len(top)} domains/organizations")
    clean_ax(ax, grid_axis="x")
    ax.legend(loc="lower right")
    plt.tight_layout()
    save_figure(out_dir, "sync_vs_reads.png", "sync_vs_reads.pdf")


if __name__ == "__main__":
    parser = make_parser(__doc__, data="./cookies_data", out="./plots/reads")
    parser.add_argument("--top_n", type=int, default=25)
    args = parser.parse_args()
    plot_synced_vs_read(args.data, args.out, args.top_n)
