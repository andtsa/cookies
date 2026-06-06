import json
from collections import defaultdict

import pandas as pd
import matplotlib.pyplot as plt

from utils import (
    apply_theme,
    save_figure,
    ACCENT,
    COLORS,
)

INPUT_FILE = "../../reads_filtered.json"
OUT_DIR = "plots"


def load_reader_coverage(path: str) -> pd.DataFrame:
    """
    Compute:
        reader_domain -> number of distinct visited domains
    """

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    reader_sites = defaultdict(set)

    for cookie_entries in data.values():

        for entry in cookie_entries:

            reader = entry.get("reader_domain")
            site = entry.get("visited_domain")

            if not reader or not site:
                continue

            reader_sites[reader].add(site)

    rows = [
        {
            "reader_domain": reader,
            "site_count": len(sites),
        }
        for reader, sites in reader_sites.items()
    ]

    return pd.DataFrame(rows)


def plot_top_readers(df: pd.DataFrame, top_n: int = 20):

    apply_theme()

    top = (
        df.sort_values("site_count", ascending=False)
        .head(top_n)
        .sort_values("site_count")
    )

    fig, ax = plt.subplots(figsize=(10, 7))

    colors = [COLORS[i % len(COLORS)] for i in range(len(top))]

    ax.barh(
        top["reader_domain"],
        top["site_count"],
        color=colors,
    )

    ax.set_title(
        f"Top {top_n} Third-Party Readers by Website Coverage"
    )

    ax.set_xlabel(
        "Distinct Websites Where Cookies Were Read"
    )

    ax.set_ylabel("Reader Domain")

    ax.grid(axis="x", alpha=0.3)

    for i, value in enumerate(top["site_count"]):
        ax.text(
            value,
            i,
            f" {value:,}",
            va="center",
        )

    plt.tight_layout()

    save_figure(
        OUT_DIR,
        "top_reader_domains.png",
        "top_reader_domains.pdf",
    )


if __name__ == "__main__":
    df = load_reader_coverage(INPUT_FILE)

    print(df.sort_values("site_count", ascending=False).head(20))

    plot_top_readers(df)