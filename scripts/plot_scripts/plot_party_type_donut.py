"""
First-Party vs Third-Party Cookie Distribution
A donut showing the percentage of first-party vs third-party cookies.

Usage:
    python scripts/plot_scripts/plot_party_type_donut.py --data cookies_data_processed --out plots
"""

import argparse
import matplotlib.pyplot as plt
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    apply_theme,
    load_cookie_data,
    BG,
    DARK,
    ACCENT,
    ACCENT2
)

def plot_party_donut(data_dir: str, out_dir: str):
    apply_theme()
    try:
        _, cookies_df = load_cookie_data(data_dir)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    if cookies_df.empty:
        print("No cookie data found.")
        return

    # Count party types
    counts = cookies_df["party_type"].value_counts()
    
    # Ensure we have both or at least handle missing ones gracefully for labeling
    labels = []
    values = []
    
    if "first_party" in counts:
        labels.append("First-Party")
        values.append(counts["first_party"])
    if "third_party" in counts:
        labels.append("Third-Party")
        values.append(counts["third_party"])
    if "unknown" in counts:
        labels.append("Unknown")
        values.append(counts["unknown"])

    total = sum(values)
    percentages = [v / total * 100 for v in values]

    # Colors: Use project palette
    # First party: Accent, Third party: Accent2, Unknown: Light/Grey
    color_map = {
        "First-Party": ACCENT,
        "Third-Party": ACCENT2,
        "Unknown": "#d8c9c0"
    }
    colors = [color_map[l] for l in labels]

    fig, ax = plt.subplots(figsize=(7, 7))

    wedges, _ = ax.pie(
        percentages,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={
            "width": 0.5,
            "edgecolor": BG,
            "linewidth": 2
        }
    )

    # Add outside labels with lines
    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2
        x = 0.98 * np.cos(np.deg2rad(angle))
        y = 0.98 * np.sin(np.deg2rad(angle))

        label_x = 1.35 * np.cos(np.deg2rad(angle))
        label_y = 1.35 * np.sin(np.deg2rad(angle))

        ax.annotate(
            f"{labels[i]}\n{percentages[i]:.1f}%",
            xy=(x, y),
            xytext=(label_x, label_y),
            ha="center",
            va="center",
            fontsize=12,
            fontweight="bold",
            color=DARK,
            arrowprops=dict(
                arrowstyle="-",
                color=DARK,
                lw=1.2
            )
        )

    ax.set_title("First-Party vs Third-Party Cookies", pad=25)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plot_party_type_donut.png")

    plt.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        facecolor=BG
    )

    print(f"Saved → {out_path}")
    plt.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="./cookies_data_processed")
    parser.add_argument("--out", default="./plots")
    args = parser.parse_args()

    plot_party_donut(args.data, args.out)
