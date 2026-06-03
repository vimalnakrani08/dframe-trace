"""dframe_trace core: capture and diff DataFrame state across pipeline steps."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .backends import snapshot as _snapshot  # backend-agnostic snapshotter


@dataclass
class Step:
    name: str
    before: Optional[dict]
    after: dict
    elapsed_ms: float
    note: str = ""

    def diff(self) -> dict:
        if self.before is None:
            return {"first_step": True}
        b, a = self.before, self.after
        added = [c for c in a["cols"] if c not in b["cols"]]
        dropped = [c for c in b["cols"] if c not in a["cols"]]
        dtype_changes = {
            c: (b["dtypes"][c], a["dtypes"][c])
            for c in a["cols"]
            if c in b["dtypes"] and b["dtypes"][c] != a["dtypes"][c]
        }
        null_changes = {
            c: (b["nulls"].get(c, 0), a["nulls"][c])
            for c in a["cols"]
            if a["nulls"][c] != b["nulls"].get(c, 0)
        }
        return {
            "rows_delta": a["rows"] - b["rows"],
            "cols_added": added,
            "cols_dropped": dropped,
            "dtype_changes": dtype_changes,
            "null_changes": null_changes,
            "mem_delta_bytes": a["mem_bytes"] - b["mem_bytes"],
        }


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)

    def record(self, name: str, before: Optional[dict], after: dict,
               elapsed_ms: float, note: str = "") -> None:
        self.steps.append(Step(name, before, after, elapsed_ms, note))

    def where_null_introduced(self, column: str) -> Optional[str]:
        """Return the name of the first step where `column` gained nulls."""
        for s in self.steps:
            d = s.diff()
            if column in d.get("null_changes", {}):
                b, a = d["null_changes"][column]
                if a > b:
                    return s.name
        return None

    def where_rows_lost(self) -> list[tuple[str, int]]:
        out = []
        for s in self.steps:
            d = s.diff()
            delta = d.get("rows_delta", 0)
            if delta < 0:
                out.append((s.name, delta))
        return out

    def report(self) -> str:
        lines = ["dframe-trace report", "=" * 60]
        for i, s in enumerate(self.steps):
            d = s.diff()
            lines.append(f"[{i}] {s.name}  ({s.elapsed_ms:.1f} ms)")
            if d.get("first_step"):
                lines.append(f"    start: {s.after['rows']} rows, "
                             f"{len(s.after['cols'])} cols")
            else:
                if d["rows_delta"]:
                    lines.append(f"    rows: {d['rows_delta']:+d}")
                if d["cols_added"]:
                    lines.append(f"    +cols: {d['cols_added']}")
                if d["cols_dropped"]:
                    lines.append(f"    -cols: {d['cols_dropped']}")
                if d["dtype_changes"]:
                    for c, (o, n) in d["dtype_changes"].items():
                        lines.append(f"    dtype {c}: {o} -> {n}")
                if d["null_changes"]:
                    for c, (o, n) in d["null_changes"].items():
                        arrow = "WARN" if n > o else "ok"
                        lines.append(f"    nulls {c}: {o} -> {n}  [{arrow}]")
            if s.note:
                lines.append(f"    note: {s.note}")
        return "\n".join(lines)


# Module-level active trace, used by the @traced decorator.
_active: Optional[Trace] = None


def traced(name: Optional[str] = None, note: str = ""):
    """Decorator: time a function that takes a df (1st arg) and returns a df,
    recording before/after snapshots onto the active trace."""
    def deco(fn: Callable):
        step_name = name or fn.__name__

        def wrapper(df, *args, **kwargs):
            before = _snapshot(df) if df is not None else None
            t0 = time.perf_counter()
            out = fn(df, *args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            if _active is not None and out is not None:
                _active.record(step_name, before, _snapshot(out), elapsed, note)
            return out
        wrapper.__name__ = step_name
        return wrapper
    return deco


class trace:  # context manager, lowercase by convention like `open`
    def __enter__(self) -> Trace:
        global _active
        self._t = Trace()
        _active = self._t
        return self._t

    def __exit__(self, *exc) -> None:
        global _active
        _active = None
        return False
