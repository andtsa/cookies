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
        `ds.filter(country="Netherlands", is_tracker=True)`).
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

        3. trackers_only: consider only tracker cookies (i.e. `is_tracker` is `True`)

        4. pass an explicit `df` to run the `group()` operation over other data (not the dataset loaded by `CookiesDataset`)
        """
        if df is not None:
            frame = df
            if where:
                for col, val in where.items():
                    frame = frame[frame[col] == val]
        else:
            cols = set(by) | ({"is_tracker"} if trackers_only else set())
            if metric != "count":
                cols.add(metric.split(":", 1)[1])
            frame = self._scan(columns=sorted(cols), where=where)
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
