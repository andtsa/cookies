"""
Shared color palette for all plots.
"""

import json
import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

BG         = "#fef2e6"
COLORS     = ["#ba4f19", "#ecb157", "#a8879d", "#ae8775",
              "#5e311d", "#ffca7b", "#fcc0a6", "#6c4633",
              "#d8c9c0", "#dfcdbb"]
ACCENT     = "#ba4f19"   # primary highlight
ACCENT2    = "#ecb157"   # secondary highlight
DARK       = "#5e311d"
MID        = "#ae8775"
LIGHT      = "#d8c9c0"

def apply_theme():
    mpl.rcParams.update({
        "figure.facecolor":  BG,
        "axes.facecolor":    BG,
        "axes.edgecolor":    DARK,
        "axes.labelcolor":   DARK,
        "axes.titlecolor":   DARK,
        "xtick.color":       DARK,
        "ytick.color":       DARK,
        "text.color":        DARK,
        "grid.color":        LIGHT,
        "grid.linewidth":    0.6,
        "font.family":       "sans-serif",
        "font.size":         11,
        "axes.titlesize":    14,
        "axes.titleweight":  "bold",
        "axes.labelsize":    11,
        "figure.dpi":        150,
        "savefig.dpi":       200,
        "savefig.bbox":      "tight",
        "savefig.facecolor": BG,
        "legend.framealpha": 0.85,
        "legend.edgecolor":  LIGHT,
    })

def load_cookie_data(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        sites_df  – one row per site  (site_metadata fields + domain)
        cookies_df – one row per cookie (all cookie fields + domain)
    """
    site_rows   = []
    cookie_rows = []

    paths = glob.glob(os.path.join(data_dir, "*.json"))
    if not paths:
        raise FileNotFoundError(f"No JSON files found in: {data_dir}")

    for path in paths:
        with open(path) as f:
            data = json.load(f)

        meta   = data.get("site_metadata", {})
        domain = os.path.basename(path).replace(".json", "")

        site_rows.append({
            "domain":           domain,
            "total_cookies":    meta.get("total_cookies", 0),
            "num_session":      meta.get("num_session", 0),
            "num_persistent":   meta.get("num_persistent", 0),
            "avg_lifetime_days": meta.get("avg_lifetime_days", 0),
            "min_lifetime_days": meta.get("min_lifetime_days", 0),
            "max_lifetime_days": meta.get("max_lifetime_days", 0),
        })

        for cookie in data.get("cookies", []):
            cookie_rows.append({
                "domain":         domain,
                "name":           cookie.get("name"),
                "session":        cookie.get("session", True),
                "cookie_type":    cookie.get("cookie_type", "session"),
                "secure":         cookie.get("secure", False),
                "httpOnly":       cookie.get("httpOnly", False),
                "sameSite":       cookie.get("sameSite"),
                "lifetime_days":  cookie.get("lifetime_days", 0),
                "party_type":     cookie.get("party_type", "unknown"),
            })

    sites_df   = pd.DataFrame(site_rows)
    cookies_df = pd.DataFrame(cookie_rows)
    return sites_df, cookies_df


BUCKETS      = ["Session", "< 1 day", "1–7 days", "8–30 days",
                "1–3 months", "3–12 months", "> 1 year"]
BUCKET_COLORS = ["#a8879d", "#d8c9c0", "#ffca7b", "#fcc0a6",
                  "#ecb157", "#ae8775", "#ba4f19"]

def lifetime_bucket(days: float, is_session: bool) -> str:
    if is_session:
        return "Session"
    if days < 1:
        return "< 1 day"
    if days <= 7:
        return "1–7 days"
    if days <= 30:
        return "8–30 days"
    if days <= 90:
        return "1–3 months"
    if days <= 365:
        return "3–12 months"
    return "> 1 year"