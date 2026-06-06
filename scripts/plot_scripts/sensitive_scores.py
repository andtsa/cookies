"""
Plot — Health Website Score Distribution
Groups websites into score categories:
0.85–0.90, 0.90–0.95, 0.95–0.99, 0.99–1.00

Usage:
    python scripts/plot_scripts/sensitive_scores.py \
        --data health_websites.csv \
        --out plots
"""

import argparse
import matplotlib.pyplot as plt
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from utils import apply_theme, save_figure, BG, DARK, MID, LIGHT


def plot_score_categories(csv_file: str, out_dir: str):
    apply_theme()

    # Load dataset
    df = pd.read_csv(csv_file)

    # Correct column name
    SCORE_COLUMN = "health_score"

    # Keep only relevant scores
    df = df[df[SCORE_COLUMN] >= 0.85].copy()

    # Define score ranges
    bins = [0.85, 0.90, 0.95, 0.99, 1.01]

    labels = [
        "0.85–0.90",
        "0.90–0.95",
        "0.95–0.99",
        "0.99–1.00",
    ]

    # Assign categories
    df["category"] = pd.cut(
        df[SCORE_COLUMN],
        bins=bins,
        labels=labels,
        include_lowest=True,
        right=False,
    )

    # Count websites per category
    counts = df["category"].value_counts().sort_index()

    # Color palette
    colors = [
        "#d8b08c",
        "#c9874f",
        "#a95c2b",
        "#7a3419",
    ]

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))

    bars = ax.bar(
        counts.index,
        counts.values,
        color=colors,
        edgecolor=BG,
        linewidth=1.0,
        width=0.7,
    )

    # Labels above bars
    for bar in bars:
        height = bar.get_height()

        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 0.5,
            f"{int(height)}",
            ha="center",
            va="bottom",
            fontsize=12,
            color=DARK,
        )

    ax.set_ylabel("Number of Websites", fontsize=13)
    ax.set_xlabel("Health Score Range", fontsize=13)

    ax.set_title(
        "Distribution of Health Website Scores",
        fontsize=16,
        pad=15,
    )

    # Styling
    ax.spines[["top", "right"]].set_visible(False)

    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()

    # Save plot
    save_figure(out_dir, "plot_health_score_categories.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data",
        default="health_websites.csv",
    )

    parser.add_argument(
        "--out",
        default="./plots",
    )

    args = parser.parse_args()

    plot_score_categories(args.data, args.out)