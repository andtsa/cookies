"""
Session vs Persistent Cookie Distribution
A donut showing the percentage of session vs persistent cookies.

Usage:
    python scripts/plot_scripts/plot_session_vs_persistent_donut.py --data cookies_data --out plots/cookie_lifetime
"""

import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    save_figure,
    make_parser,
    donut_chart,
    BUCKET_COLORS,
)


def plot_donut(data_dir: str, out_dir: str) -> None:
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)
    total = len(cookies_df)
    n_session = int(cookies_df["session"].sum())
    n_persistent = total - n_session

    fig, ax = plt.subplots(figsize=(7, 7))
    donut_chart(
        ax,
        ["Session", "Persistent"],
        [n_session / total * 100, n_persistent / total * 100],
        [BUCKET_COLORS[0], BUCKET_COLORS[-1]],
    )
    ax.set_title("Session vs Persistent Cookies", pad=15)
    save_figure(out_dir, "plot_session_persistent_donut.png")


if __name__ == "__main__":
    args = make_parser(out="./plots/cookie_lifetime").parse_args()
    plot_donut(args.data, args.out)
