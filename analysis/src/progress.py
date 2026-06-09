"""
Tiny optional-tqdm wrapper used to show progress across the annotation stages.

``track`` wraps an iterable in a tqdm progress bar when ``tqdm`` is installed and
silently returns the iterable unchanged when it is not — so progress bars are a
zero-cost, soft dependency. Bars are emitted for every dataset build (the loops
that dominate the complexity table: loading sites, EasyPrivacy matching, frame
construction, the relational passes, and classification), writing to ``stderr``
so they never contaminate data written to ``stdout``.
"""

from __future__ import annotations

from typing import Iterable, Optional, TypeVar

T = TypeVar("T")

__all__ = ["track", "bar"]


def track(
    iterable: Iterable[T],
    desc: str = "",
    total: Optional[int] = None,
    unit: str = "it",
    leave: bool = True,
) -> Iterable[T]:
    """Wrap ``iterable`` in a tqdm bar, or return it untouched if tqdm is absent."""
    try:
        from tqdm.auto import tqdm
    except Exception:
        return iterable
    return tqdm(iterable, desc=desc, total=total, unit=unit, leave=leave)


def bar(desc: str = "", total: Optional[int] = None, unit: str = "it", leave: bool = True):
    """Return a manually-updated tqdm bar, or a no-op stand-in if tqdm is absent.

    The stand-in supports ``update``, ``set_postfix``/``set_postfix_str`` and the
    context-manager protocol, so call sites need no ``if tqdm`` branching.
    """
    try:
        from tqdm.auto import tqdm
    except Exception:
        return _NullBar()
    return tqdm(desc=desc, total=total, unit=unit, leave=leave)


class _NullBar:
    """No-op fallback matching the slice of the tqdm API used here."""

    def update(self, n: int = 1) -> None:  # noqa: D401
        pass

    def set_postfix(self, *args, **kwargs) -> None:
        pass

    def set_postfix_str(self, *args, **kwargs) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> "_NullBar":
        return self

    def __exit__(self, *exc) -> None:
        pass
