"""
Preliminary Religious Website Classification Results
A donut chart showing how websites from the Religion dataset
were classified by the sensitivity classifier.

Usage:
    python scripts/plot_scripts/plot_religion_classification_donut.py --out plots
"""

import argparse
import matplotlib.pyplot as plt
import numpy as np
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(CURRENT_DIR)

from utils import (
    apply_theme,
    BG,
    DARK,
    ACCENT,
    ACCENT2
)
def plot_religion_classification(out_dir: str):
    apply_theme()

    # Preliminary classification results
    labels = [
        "Religion",
        "Health",
        "Non-Sensitive"
    ]

    values = [
        79,
        3,
        11
    ]

    total = sum(values)
    percentages = [v / total * 100 for v in values]

    # Project palette
    colors = [
        ACCENT,       # Religion
        ACCENT2,      # Health
        "#d8c9c0"     # Non-Sensitive
    ]

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

    # Add outside labels with connector lines
    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2

        x = 0.98 * np.cos(np.deg2rad(angle))
        y = 0.98 * np.sin(np.deg2rad(angle))

        label_x = 1.35 * np.cos(np.deg2rad(angle))
        label_y = 1.35 * np.sin(np.deg2rad(angle))

        ax.annotate(
            f"{labels[i]}\n{values[i]} ({percentages[i]:.1f}%)",
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

    ax.set_title(
        "Religious Websites Dataset",
        pad=25
    )

    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(
        out_dir,
        "plot_religion_classification_donut.png"
    )

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

    parser.add_argument(
        "--out",
        default="./plots"
    )

    args = parser.parse_args()

    plot_religion_classification(args.out)