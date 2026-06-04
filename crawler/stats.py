import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import psutil


class CrawlStats:
    def __init__(self, start_index: int, concurrency: int):
        self._lock = asyncio.Lock()
        self.start_index = start_index
        self.concurrency = concurrency
        self.start_time = time.monotonic()
        self.start_wall = datetime.now(timezone.utc)
        self.completed = 0
        self.errors = 0
        self.skipped = 0
        self._visit_count = 0
        self._visit_sum = 0.0
        self._visit_min = float("inf")
        self._visit_max = 0.0
        # rolling window of (monotonic_time, completed_count) for throughput
        self._samples: list[tuple[float, int]] = []
        self._WINDOW_S = 600  # 10-minute rolling window
        # set by throttle monitor, reflected in stats.json
        self.active_throttle: bool = False

    async def record_completion(self) -> int:
        """Increment completed count; return new value."""
        async with self._lock:
            self.completed += 1
            n = self.completed
            now = time.monotonic()
            self._samples.append((now, n))
            cutoff = now - self._WINDOW_S
            self._samples = [s for s in self._samples if s[0] >= cutoff]
            return n

    async def record_visit(self, elapsed: float, success: bool) -> None:
        async with self._lock:
            if success:
                self._visit_count += 1
                self._visit_sum += elapsed
                self._visit_min = min(self._visit_min, elapsed)
                self._visit_max = max(self._visit_max, elapsed)
            else:
                self.errors += 1

    async def record_skip(self) -> None:
        async with self._lock:
            self.skipped += 1

    def sites_per_min(self) -> float:
        now = time.monotonic()
        recent = [s for s in self._samples if s[0] >= now - self._WINDOW_S]
        if len(recent) >= 2:
            dc = recent[-1][1] - recent[0][1]
            dt = (recent[-1][0] - recent[0][0]) / 60.0
            return dc / dt if dt > 0.01 else 0.0
        elapsed_min = (now - self.start_time) / 60.0
        return self.completed / elapsed_min if elapsed_min > 0.01 else 0.0

    def to_dict(self, total_sites: Optional[int] = None) -> dict:
        spm = self.sites_per_min()
        remaining = (
            (total_sites - self.start_index - self.completed) if total_sites else None
        )
        eta_h = (remaining / spm / 60.0) if (spm and remaining) else None
        avg_s = self._visit_sum / self._visit_count if self._visit_count else None
        try:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent()  # non-blocking; kept fresh by throttle monitor
            mem_gb = mem.available / 1024**3
        except Exception:
            cpu = mem_gb = None
        return {
            "started_at": self.start_wall.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "progress": {
                "completed": self.completed,
                "start_index": self.start_index,
                "errors": self.errors,
                "skipped": self.skipped,
                "total": total_sites,
            },
            "throughput": {
                "sites_per_min": round(spm, 2),
                "eta_hours": round(eta_h, 1) if eta_h is not None else None,
            },
            "timing": {
                "avg_visit_s": round(avg_s, 2) if avg_s is not None else None,
                "min_visit_s": (
                    round(self._visit_min, 2) if self._visit_count else None
                ),
                "max_visit_s": (
                    round(self._visit_max, 2) if self._visit_count else None
                ),
            },
            "resources": {
                "concurrency": self.concurrency,
                "cpu_pct": cpu,
                "mem_available_gb": (round(mem_gb, 2) if mem_gb is not None else None),
                "active_throttle": self.active_throttle,
            },
        }

    def write(self, path: str, total_sites: Optional[int] = None) -> None:
        """Atomically write stats.json — same pattern as client/output.py."""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(total_sites), f, indent=2)
        os.replace(tmp, path)

    def checkpoint_line(self) -> str:
        spm = self.sites_per_min()
        avg_s = self._visit_sum / self._visit_count if self._visit_count else 0.0
        now = datetime.now().strftime("%H:%M")
        return (
            f"[Crawler] {self.completed} done | {spm:.1f} sites/min | "
            f"{self.errors} errors | {self.skipped} skipped | avg {avg_s:.1f}s/site [{now}]"
        )
