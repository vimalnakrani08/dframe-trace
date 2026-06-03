"""dframe_trace.backends: structural snapshots across DataFrame libraries.

Each backend turns a frame into the same plain dict so core/guards stay
library-agnostic:

    {"rows": int, "cols": [str], "dtypes": {col: str},
     "nulls": {col: int}, "mem_bytes": int}

Detection is duck-typed and import-light: we never import pandas or polars
ourselves; we inspect the object's type module instead. This keeps dframe_trace
dependency-free and avoids importing a library the user isn't even using.
"""
from __future__ import annotations

from typing import Optional


def _module_root(obj) -> str:
    return type(obj).__module__.split(".", 1)[0]


def snapshot(df) -> Optional[dict]:
    """Return a structural snapshot, or None if the object isn't a supported
    frame (e.g. a polars LazyFrame, a GroupBy, or something unrelated)."""
    if df is None:
        return None
    root = _module_root(df)
    if root == "pandas":
        return _snapshot_pandas(df)
    if root == "polars":
        return _snapshot_polars(df)
    # Unknown object: try the pandas-like protocol, else give up gracefully.
    return _snapshot_duck(df)


# --------------------------------------------------------------------------- #
# pandas
# --------------------------------------------------------------------------- #
def _snapshot_pandas(df) -> Optional[dict]:
    try:
        cols = list(df.columns)
        return {
            "rows": int(len(df)),
            "cols": [str(c) for c in cols],
            "dtypes": {str(c): str(df[c].dtype) for c in cols},
            "nulls": {str(c): int(df[c].isna().sum()) for c in cols},
            "mem_bytes": int(df.memory_usage(deep=True).sum()),
        }
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# polars (eager DataFrame only; LazyFrame is intentionally skipped -- see note)
# --------------------------------------------------------------------------- #
def _snapshot_polars(df) -> Optional[dict]:
    # LazyFrame has no cheap row count or null count: materializing it just to
    # trace would change the program's performance characteristics and could
    # trigger expensive scans. We skip it and let the caller record nothing;
    # autopatch handles lazy frames by tracing at .collect() instead.
    if type(df).__name__ == "LazyFrame":
        return None
    try:
        cols = list(df.columns)
        # polars null_count() returns a 1-row DataFrame, one column per column.
        # Access is [col][0]; fall back to to_dicts() if indexing differs across
        # polars versions.
        nc = df.null_count()
        try:
            nulls = {c: int(nc[c][0]) for c in cols}
        except Exception:
            row = nc.to_dicts()[0]
            nulls = {c: int(row.get(c, 0)) for c in cols}
        dtypes = {c: str(dt) for c, dt in zip(cols, df.dtypes)}
        try:
            mem = int(df.estimated_size())
        except Exception:
            mem = 0
        return {
            "rows": int(df.height),
            "cols": [str(c) for c in cols],
            "dtypes": dtypes,
            "nulls": nulls,
            "mem_bytes": mem,
        }
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# duck-typed fallback (anything exposing a pandas-like surface)
# --------------------------------------------------------------------------- #
def _snapshot_duck(df) -> Optional[dict]:
    if not (hasattr(df, "columns") and hasattr(df, "__len__")):
        return None
    try:
        cols = list(df.columns)
        out = {
            "rows": int(len(df)),
            "cols": [str(c) for c in cols],
            "dtypes": {},
            "nulls": {},
            "mem_bytes": 0,
        }
        for c in cols:
            try:
                out["dtypes"][str(c)] = str(df[c].dtype)
            except Exception:
                out["dtypes"][str(c)] = "?"
            try:
                out["nulls"][str(c)] = int(df[c].isna().sum())
            except Exception:
                out["nulls"][str(c)] = 0
        try:
            out["mem_bytes"] = int(df.memory_usage(deep=True).sum())
        except Exception:
            pass
        return out
    except Exception:
        return None
