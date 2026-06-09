"""
Health vs. non-health website tracker comparison (NL crawl, Chromium).
File location: scripts/plot_scripts/plot_health_vs_all.py

Usage:
  python plot_health_vs_all.py                # full dataset (slow)
  python plot_health_vs_all.py --sample 2000  # random 2000 non-health sites (fast)
"""

import os, sys, csv, shutil, tempfile, argparse, random
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches

_MAX_WORKERS = int(os.environ.get("COOKIE_WORKERS", "4"))
os.cpu_count = lambda: _MAX_WORKERS + 1

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from utils import apply_theme, save_figure, dataset, ACCENT, ACCENT2, DARK, LIGHT, MID, BG


# ── file index helpers ────────────────────────────────────────────────────────

def load_health_domains(csv_path):
    domains = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            domains.add(row["domain"].strip().lower())
    return domains


def domain_to_filename(domain):
    return domain.replace(".", "_") + ".json"


def build_index(data_dir):
    index = {}
    for subdir in os.listdir(data_dir):
        subpath = os.path.join(data_dir, subdir)
        if not os.path.isdir(subpath):
            continue
        for fname in os.listdir(subpath):
            if fname.endswith(".json"):
                index[fname] = os.path.join(subpath, fname)
    return index


def build_data_dir(file_paths):
    tmp = tempfile.mkdtemp(prefix="cookies_subset_")
    for src in file_paths:
        subdir  = os.path.basename(os.path.dirname(src))
        fname   = os.path.basename(src)
        dst_dir = os.path.join(tmp, subdir)
        os.makedirs(dst_dir, exist_ok=True)
        try:
            os.symlink(src, os.path.join(dst_dir, fname))
        except (OSError, NotImplementedError):
            shutil.copy2(src, os.path.join(dst_dir, fname))
    return tmp


# ── cookie prep ───────────────────────────────────────────────────────────────

def load_and_prep(tmp_dir, label):
    print(f"Loading {label}...")
    ds = dataset(tmp_dir)
    c  = ds.cookies.copy()
    dc = "bare_domain" if "bare_domain" in c.columns else "domain"
    c[dc] = c[dc].str.lstrip(".").str.lower()
    print(f"  {label}: {c[dc].nunique()} sites, {len(c)} cookies total")
    return c, dc


def tracker_rows(cookies, dc):
    if "is_tracker" in cookies.columns:
        return cookies[cookies["is_tracker"].astype(bool)].copy()
    return cookies.copy()


def with_provider(t, dc):
    pc  = next((c for c in ("tracker_provider","provider","cookie_provider") if c in t.columns), None)
    cdn = "domain" if "domain" in t.columns else dc
    t   = t.copy()
    t["_provider"] = (
        t[pc].fillna(t[cdn].str.lstrip(".")) if pc
        else t[cdn].str.lstrip(".")
    )
    return t[t["_provider"].str.contains(r"\.", regex=True, na=False)]


# ── panels ────────────────────────────────────────────────────────────────────

def panel_session_split(ax, h_t, n_t):
    """
    A: Stacked bar — three categories of tracker cookies:
       - Session: lifetime == 0, expire at the end of the session
       - Short-lived: lifetime_days <= 1 (expires within a day or less)
       - Persistent:  lifetime_days >  1
    Shows as % of all tracker cookies in each group.
    """
    lt = "lifetime_days"
    if lt not in h_t.columns:
        ax.text(0.5, 0.5, "lifetime_days not available",
                ha="center", va="center", transform=ax.transAxes, color=DARK)
        ax.set_title("A   Tracker Cookie Lifetime Categories",
                     fontweight="bold", color=DARK)
        return

    def split(t):
        total = len(t)
        session = t[lt].isna().sum()
        short = ((t[lt] > 0) & (t[lt] <= 1)).sum()
        persistent = (t[lt] > 1).sum()
        return session / total * 100, short / total * 100, persistent / total * 100

    h_sess, h_short, h_pers = split(h_t)
    n_sess, n_short, n_pers = split(n_t)

    x = np.arange(2)
    w = 0.45
    se_v = [n_sess, h_sess]
    sh_v = [n_short, h_short]
    p_v = [n_pers, h_pers]

    ax.bar(x, se_v, w, color=LIGHT, label="Session (no expiry date)")
    ax.bar(x, sh_v, w, bottom=se_v, color=MID, label="Short-lived persistent (≤ 1 day)")
    ax.bar(x, p_v, w, bottom=[s + sh for s, sh in zip(se_v, sh_v)],
           color=ACCENT, label="Persistent (> 1 day)")

    for i, (sev, shv, pv) in enumerate(zip(se_v, sh_v, p_v)):
        bottom = 0
        for val, col in [(sev, DARK), (shv, DARK), (pv, "white")]:
            if val > 2:
                ax.text(i, bottom + val / 2, f"{val:.1f}%",
                        ha="center", va="center", fontsize=9,
                        fontweight="bold", color=col)
            bottom += val

    ax.set_xticks(x)
    ax.set_xticklabels(["Non-health", "Health"])
    ax.set_ylabel("% of Tracker Cookies")
    ax.set_ylim(0, 110)
    ax.legend(fontsize=8.5, loc="upper right")
    ax.set_title("A   Tracker Cookie Lifetime Categories",
                 fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)

def panel_tracker_count(ax, h_cook, n_cook, h_dc, n_dc, h_total, n_total,
                         thresholds=(1, 3, 5, 10)):
    """B: % of sites with at least N tracker cookies."""
    def frac_above(cookies, dc, total, thresh):
        if "is_tracker" in cookies.columns:
            per_site = cookies[cookies["is_tracker"].astype(bool)].groupby(dc).size()
        else:
            per_site = cookies.groupby(dc).size()
        return (per_site >= thresh).sum() / total * 100

    x   = np.arange(len(thresholds))
    w   = 0.35
    h_v = [frac_above(h_cook, h_dc, h_total, t) for t in thresholds]
    n_v = [frac_above(n_cook, n_dc, n_total, t) for t in thresholds]

    ax.bar(x - w/2, n_v, w, color=ACCENT2, label="Non-health")
    ax.bar(x + w/2, h_v, w, color=ACCENT,  label="Health")
    ax.set_xticks(x)
    ax.set_xticklabels([f"≥{t} trackers" for t in thresholds])
    ax.set_ylabel("% of Sites")
    ax.legend(fontsize=9)
    ax.set_title("B   Tracker Cookies per Site", fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)
    for xi, (nv, hv) in enumerate(zip(n_v, h_v)):
        ax.text(xi - w/2, nv + 0.4, f"{nv:.1f}%", ha="center", fontsize=7.5, color=DARK)
        ax.text(xi + w/2, hv + 0.4, f"{hv:.1f}%", ha="center", fontsize=7.5, color=DARK)


def panel_providers_diff(ax, h_t, n_t, h_total, n_total, top_n):
    """C: Diverging bar — providers where health and non-health differ most."""
    dc_h = [c for c in h_t.columns if c in ("bare_domain","domain")][0]
    dc_n = [c for c in n_t.columns if c in ("bare_domain","domain")][0]

    h_prev = h_t.groupby("_provider")[dc_h].nunique() / h_total * 100
    n_prev = n_t.groupby("_provider")[dc_n].nunique() / n_total * 100

    all_p = set(h_prev.index) | set(n_prev.index)
    diff  = {p: h_prev.get(p, 0) - n_prev.get(p, 0) for p in all_p}
    top   = sorted(diff.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]
    top   = sorted(top, key=lambda x: x[1])

    providers = [d[0] for d in top]
    values    = [d[1] for d in top]
    colors    = [ACCENT if v > 0 else ACCENT2 for v in values]

    y = np.arange(len(providers))
    ax.barh(y, values, color=colors, height=0.65)
    ax.set_yticks(y)
    ax.set_yticklabels(providers, fontsize=8.5)
    ax.axvline(0, color=DARK, linewidth=0.8)
    ax.set_xlabel("Difference in tracker providers prevalence between health and non-health sites\n"
                  "(positive = more common on health sites, negative = more common on non-health sites)")
    ax.legend(handles=[
        mpatches.Patch(color=ACCENT,  label="More prevalent on health sites"),
        mpatches.Patch(color=ACCENT2, label="More prevalent on non-health sites"),
    ], fontsize=8, loc="lower right")
    ax.set_title("C   Tracker Providers in Health vs Non-Health Sites",
                 fontweight="bold", color=DARK)
    ax.spines[["top", "right"]].set_visible(False)


def panel_lifetime_split(ax_h, ax_n, h_t, n_t):
    """D: Two stacked histograms of persistent cookie lifetime."""
    lt = "lifetime_days"
    if lt not in h_t.columns:
        for ax in (ax_h, ax_n):
            ax.text(0.5, 0.5, "lifetime_days not available",
                    ha="center", va="center", transform=ax.transAxes)
        return

    h_lt = h_t.loc[h_t[lt] > 1, lt].clip(upper=400)
    n_lt = n_t.loc[n_t[lt] > 1, lt].clip(upper=400)
    bins = np.linspace(0, 400, 41)

    for ax, data, label, color in [
        (ax_h, h_lt, "Health Sites",     ACCENT),
        (ax_n, n_lt, "Non-health Sites", ACCENT2),
    ]:
        ax.hist(data, bins=bins, color=color, alpha=0.85)
        med = data.median()
        ax.axvline(med, color=DARK, linestyle="--", linewidth=1.4,
                   label=f"Median: {med:.0f} days")
        ax.axvline(365, color=LIGHT, linestyle=":", linewidth=1.2, label="1 year")
        ax.set_ylabel("Cookie Count")
        # ax.set_title(label, fontsize=10, color=DARK)
        ax.legend(fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    ax_n.set_xlabel("Persistent Cookie Lifetime (days, capped at 400)")
    ax_h.set_xticklabels([])
    ax_h.set_title("D   Persistent Tracker Cookie Lifetime", fontweight="bold", color=DARK)
    ax_h.set_title("D   Persistent Tracker Cookie Lifetime", fontweight="bold", color=DARK)
    ax_h.text(0.5, 0.97, "(Health Sites)", transform=ax_h.transAxes,
          ha="center", va="top", fontsize=10, color=DARK, fontweight="bold",
          bbox=dict(facecolor=BG, edgecolor="none", pad=2))
    ax_n.text(0.5, 0.97, "(Non-health Sites)", transform=ax_n.transAxes,
              ha="center", va="top", fontsize=10, color=DARK, fontweight="bold")
    # ax_h.text(0.5, 1.05, "(Health Sites)", transform=ax_h.transAxes,
    #           ha="center", va="bottom", fontsize=10, color=DARK, fontweight="bold")
    # ax_n.set_title("(Non-health Sites)", fontsize=10, color=DARK)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top_n",   type=int, default=12)
    parser.add_argument("--workers", type=int, default=_MAX_WORKERS)
    parser.add_argument("--sample",  type=int, default=None, metavar="N",
                        help="Randomly sample N non-health sites. Omit for full dataset.")
    parser.add_argument("--seed",    type=int, default=42)
    args = parser.parse_args()
    os.cpu_count = lambda: args.workers + 1

    full_data_dir = os.path.join(ROOT, "cookies_data", "Netherlands", "chromium")
    csv_path      = os.path.join(ROOT, "health_websites_1K.csv")
    out_dir       = os.path.join(ROOT, "plots", "health_vs_all")
    os.makedirs(out_dir, exist_ok=True)

    health_domains = load_health_domains(csv_path)
    health_fnames  = {domain_to_filename(d) for d in health_domains}
    print(f"Loaded {len(health_domains)} health domains")

    print("Building filename index...")
    index = build_index(full_data_dir)
    print(f"Index: {len(index):,} JSON files")

    health_files    = [p for f, p in index.items() if f in health_fnames]
    nonhealth_files = [p for f, p in index.items() if f not in health_fnames]
    print(f"Health files: {len(health_files)}, non-health: {len(nonhealth_files)}")

    if args.sample is not None:
        random.seed(args.seed)
        nonhealth_files = random.sample(nonhealth_files, min(args.sample, len(nonhealth_files)))
        print(f"[sample mode] {len(nonhealth_files)} non-health sites (seed={args.seed})")

    h_tmp = build_data_dir(health_files)
    n_tmp = build_data_dir(nonhealth_files)

    try:
        h_cook, h_dc = load_and_prep(h_tmp, "health")
        n_cook, n_dc = load_and_prep(n_tmp, "non-health")

        h_total = h_cook[h_dc].nunique()
        n_total = n_cook[n_dc].nunique()

        h_t = with_provider(tracker_rows(h_cook, h_dc), h_dc)
        n_t = with_provider(tracker_rows(n_cook, n_dc), n_dc)

        print(f"Health tracker cookies: {len(h_t):,}, non-health: {len(n_t):,}")

        sample_note = (f", random sample of {len(nonhealth_files)} non-health sites"
                       if args.sample else "")

        apply_theme()

        fig = plt.figure(figsize=(16, 12))
        gs_outer = gridspec.GridSpec(2, 2, figure=fig, hspace=0.22, wspace=0.22)

        ax_a  = fig.add_subplot(gs_outer[0, 0])
        ax_b  = fig.add_subplot(gs_outer[0, 1])
        ax_c  = fig.add_subplot(gs_outer[1, 0])
        gs_d  = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs_outer[1, 1],
                                                  hspace=0.1)
        ax_dh = fig.add_subplot(gs_d[0])
        ax_dn = fig.add_subplot(gs_d[1])

        panel_session_split(ax_a, h_t, n_t)
        panel_tracker_count(ax_b, h_cook, n_cook, h_dc, n_dc, h_total, n_total)
        panel_providers_diff(ax_c, h_t, n_t, h_total, n_total, args.top_n)
        panel_lifetime_split(ax_dh, ax_dn, h_t, n_t)

        fig.suptitle(
            "Tracker Activity on Health Websites vs Non-Health Websites",
            fontsize=16, fontweight="bold", color=DARK, y=0.96,
        )
        fig.text(
            0.5, 0.93,
            f"{h_total} health sites vs {n_total} non-health sites. "
            f"Ran from the Netherlands with Chromium{sample_note}",
            ha="center", fontsize=13, color=MID,
        )

        save_figure(out_dir, "health_vs_nonhealth_trackers.png")

    finally:
        shutil.rmtree(h_tmp, ignore_errors=True)
        shutil.rmtree(n_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()