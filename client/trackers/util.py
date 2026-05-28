import os
import re
from typing import Optional


def _cache_filename(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", url) + ".txt"


def _load_from_cache(url: str, cache_dir: str) -> Optional[str]:
    path = os.path.join(cache_dir, _cache_filename(url))
    if not os.path.exists(path):
        return None
    print(f"[TrackerList] Using cached list: {path}")
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _save_to_cache(url: str, cache_dir: str, text: str) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, _cache_filename(url))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"[TrackerList] cached {path}")
