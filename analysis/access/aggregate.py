from __future__ import annotations

import pandas as pd


# specifically for accessing cookies.
class AggregateAccess:
    def _scan(
        self, columns: list[str] | None = None, where: dict | None = None
    ) -> pd.DataFrame:
        df = self.cookies
        if where:
            for col, val in where.items():
                df = df[df[col] == val]
        return df[list(columns)] if columns else df

    def filter(self, **conditions) -> pd.DataFrame:
        """Rows of `cookies` matching every `column=value` pair (e.g.
        `ds.filter(country="Netherlands", is_tracker_listed=True)`).

        Note: ``is_tracker_listed`` is the raw list-membership boolean on
        :attr:`cookies`. For the classification-based canonical boolean use
        :attr:`classified_cookies` directly and filter on ``is_tracker``.
        """
        return self._scan(where=conditions)

    def group(
        self,
        by: list[str],
        metric: str = "count",
        *,
        where: dict | None = None,
        trackers_only: bool = False,
        df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generic group-by reduction

        arguments:

        1. `metric` is
            - `"count"`,
            - `"nunique:<col>"` or
            - `"<agg>:<col>"`,
                and `<agg>` is any pandas aggregation (``mean``, ``sum``, etc).

        2. `where` pre-filters by `column=value` pairs

        3. `trackers_only`: restrict to cookies where ``is_tracker`` is ``True`` —
           the unified classification-based boolean (``tracker_tier >= "probable"``).
           Uses :attr:`classified_cookies` as the source frame so the definition
           is consistent with any direct access to that frame.

        4. pass an explicit `df` to run the `group()` operation over other data (not the dataset loaded by `CookiesDataset`)
        """
        if df is not None:
            frame = df
            if where:
                for col, val in where.items():
                    frame = frame[frame[col] == val]
        elif trackers_only:
            # classified_cookies is the canonical source for is_tracker
            # (tier >= probable). Don't go through _scan/cookies here — that
            # frame carries the list-only is_tracker, not the unified one.
            frame = self.classified_cookies
            if where:
                for col, val in where.items():
                    frame = frame[frame[col] == val]
        else:
            cols = set(by)
            if metric != "count":
                cols.add(metric.split(":", 1)[1])
            frame = self._scan(columns=sorted(cols) if cols else None, where=where)
        if trackers_only:
            frame = frame[frame["is_tracker"]]
        grouped = frame.groupby(by, dropna=False)
        if metric == "count":
            out = grouped.size().reset_index(name="value")
        elif metric.startswith("nunique:"):
            col = metric.split(":", 1)[1]
            out = grouped[col].nunique().reset_index(name="value")
        else:
            agg, col = metric.split(":", 1)
            out = grouped[col].agg(agg).reset_index(name="value")
        return out
