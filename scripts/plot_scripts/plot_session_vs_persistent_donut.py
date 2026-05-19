"""
Session vs Persistent Cookie Distribution
A donut showing the percentage of session vs persistent cookies.

Usage:
    python scripts/plot_scripts/plot_session_vs_persistent_donut.py --data cookies_data --out plots/cookie_lifetime
"""

import argparse
import matplotlib.pyplot as plt
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import apply_theme, load_cookie_data, BG, DARK, BUCKET_COLORS


def plot_donut(data_dir: str, out_dir: str):
    apply_theme()
    _, cookies_df = load_cookie_data(data_dir)

    total = len(cookies_df)

    session_count = cookies_df["session"].sum()
    persistent_count = total - session_count

    session_pct = session_count / total * 100
    persistent_pct = persistent_count / total * 100

    values = [session_pct, persistent_pct]
    labels = ["Session", "Persistent"]

    colors = [BUCKET_COLORS[0], BUCKET_COLORS[-1]]

    fig, ax = plt.subplots(figsize=(7, 7))

    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.5, "edgecolor": BG, "linewidth": 2},
    )

    # Add outside labels with lines
    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2
        x = 0.98 * np.cos(np.deg2rad(angle))
        y = 0.98 * np.sin(np.deg2rad(angle))

        label_x = 1.25 * np.cos(np.deg2rad(angle))
        label_y = 1.25 * np.sin(np.deg2rad(angle))

        ax.annotate(
            f"{labels[i]}\n{values[i]:.1f}%",
            xy=(x, y),
            xytext=(label_x, label_y),
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=DARK,
            arrowprops=dict(arrowstyle="-", color=DARK, lw=1.2),
        )

    ax.set_title("Session vs Persistent Cookies", pad=15)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_session_persistent_donut.png")

    plt.savefig(out_path, dpi=300, bbox_inches="tight", facecolor=BG)

    print(f"Saved → {out_path}")
    plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookie_data")
    parser.add_argument("--out", default="./plots")
    args = parser.parse_args()

    plot_donut(args.data, args.out)
