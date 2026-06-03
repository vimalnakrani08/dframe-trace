"""dframe_trace.autopatch: zero-decorator tracing for pandas and polars.

Monkeypatches the DataFrame methods that most often cause silent data bugs so
that any call inside an active `trace()` block is recorded automatically.

    from dframe_trace import trace
    import dframe_trace.autopatch as ap

    ap.install()                 # patches whichever of pandas/polars is present
    with trace() as t:
        df = raw.merge(meta, how="left")   # pandas: recorded automatically
        out = lf.filter(...).collect()     # polars: recorded at collect()
    print(t.report())
    ap.uninstall()

Design notes
------------
* pandas: every patched method returns a DataFrame; we snapshot input vs output.
* polars eager (DataFrame): same approach as pandas.
* polars lazy (LazyFrame): intermediate steps build a query plan and cannot be
  snapshotted cheaply, so we trace at `.collect()` -- the point where the plan
  materializes into a real frame. The recorded step is named "collect".
* Recording only happens while a trace is active; otherwise the wrapper is a
  single `is None` check, so leaving it installed in production is cheap.
* pandas and polars are both optional. We patch only what is importable.
"""
from __future__ import annotations

import functools
import time
from typing import Optional

from . import core

# pandas DataFrame methods that return a DataFrame and are common bug sources.
_PANDAS_TARGETS = [
    "merge", "join", "dropna", "fillna", "astype", "drop",
    "rename", "query", "sort_values", "reset_index", "assign",
    "drop_duplicates", "set_index",
]

# polars eager DataFrame methods worth tracing (all return a new DataFrame).
_POLARS_DF_TARGETS = [
    "join", "drop_nulls", "fill_null", "cast", "drop",
    "rename", "filter", "sort", "unique", "with_columns", "select",
]

# polars LazyFrame: trace only at the materialization boundary.
_POLARS_LF_TARGETS = ["collect"]

_originals: list = []  # (owner, name, original) for restoration
_installed = False


def _make_method_wrapper(method_name, original):
    """Wrap a method that takes a frame as self and returns a frame."""
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        active = core._active
        if active is None:
            return original(self, *args, **kwargs)
        before = core._snapshot(self)
        t0 = time.perf_counter()
        out = original(self, *args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        try:
            after = core._snapshot(out)
            if after is not None:
                active.record(method_name, before, after, elapsed, note="auto")
        except Exception:
            pass
        return out

    wrapper._dframe_trace_patched = True
    return wrapper


def _make_collect_wrapper(original):
    """Wrap LazyFrame.collect: no cheap 'before' for a lazy plan, so record the
    materialized result with before=None (treated as a fresh step)."""
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        active = core._active
        if active is None:
            return original(self, *args, **kwargs)
        t0 = time.perf_counter()
        out = original(self, *args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        try:
            after = core._snapshot(out)
            if after is not None:
                active.record("collect", None, after, elapsed, note="auto-lazy")
        except Exception:
            pass
        return out

    wrapper._dframe_trace_patched = True
    return wrapper


def install(pandas: bool = True, polars: bool = True) -> None:
    """Patch whichever libraries are installed. Idempotent and safe to call
    when a library is absent."""
    global _installed

    if pandas:
        try:
            import pandas as pd
            for name in _PANDAS_TARGETS:
                orig = getattr(pd.DataFrame, name, None)
                if orig is not None and not getattr(orig, "_dframe_trace_patched", False):
                    _originals.append((pd.DataFrame, name, orig))
                    setattr(pd.DataFrame, name, _make_method_wrapper(name, orig))
        except ImportError:
            pass

    if polars:
        try:
            import polars as pl
            for name in _POLARS_DF_TARGETS:
                orig = getattr(pl.DataFrame, name, None)
                if orig is not None and not getattr(orig, "_dframe_trace_patched", False):
                    _originals.append((pl.DataFrame, name, orig))
                    setattr(pl.DataFrame, name, _make_method_wrapper(name, orig))
            for name in _POLARS_LF_TARGETS:
                orig = getattr(pl.LazyFrame, name, None)
                if orig is not None and not getattr(orig, "_dframe_trace_patched", False):
                    _originals.append((pl.LazyFrame, name, orig))
                    setattr(pl.LazyFrame, name, _make_collect_wrapper(orig))
        except ImportError:
            pass

    _installed = True


def uninstall() -> None:
    """Restore all original methods."""
    global _installed
    for owner, name, original in _originals:
        setattr(owner, name, original)
    _originals.clear()
    _installed = False


def is_installed() -> bool:
    return _installed
