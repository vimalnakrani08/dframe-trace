"""dframe_trace.guards: assertions that turn a trace into a CI gate.

    with trace() as t:
        ... pipeline ...
    guards.assert_no_new_nulls(t)        # raises if any step introduced nulls
    guards.assert_no_row_loss(t)         # raises if any step dropped rows
    guards.assert_no_silent_casts(t)     # raises on unexpected dtype changes
"""
from __future__ import annotations

from .core import Trace


class TraceAssertionError(AssertionError):
    """Raised when a guard finds a violation. Carries structured detail."""

    def __init__(self, message: str, violations: list):
        super().__init__(message)
        self.violations = violations


def assert_no_new_nulls(trace: Trace, columns: list[str] | None = None) -> None:
    violations = []
    for s in trace.steps:
        for col, (before, after) in s.diff().get("null_changes", {}).items():
            if columns is not None and col not in columns:
                continue
            if after > before:
                violations.append((s.name, col, after - before))
    if violations:
        detail = ", ".join(f"{step} introduced {n} null(s) in '{col}'"
                           for step, col, n in violations)
        raise TraceAssertionError(f"new nulls detected: {detail}", violations)


def assert_no_row_loss(trace: Trace, allow: set[str] | None = None) -> None:
    allow = allow or set()
    violations = [(s.name, s.diff()["rows_delta"]) for s in trace.steps
                  if s.diff().get("rows_delta", 0) < 0 and s.name not in allow]
    if violations:
        detail = ", ".join(f"{step} dropped {-d} row(s)" for step, d in violations)
        raise TraceAssertionError(f"row loss detected: {detail}", violations)


def assert_no_silent_casts(trace: Trace, allow: set[str] | None = None) -> None:
    allow = allow or set()
    violations = []
    for s in trace.steps:
        if s.name in allow:
            continue
        for col, (old, new) in s.diff().get("dtype_changes", {}).items():
            violations.append((s.name, col, old, new))
    if violations:
        detail = ", ".join(f"{step} cast '{col}' {old}->{new}"
                           for step, col, old, new in violations)
        raise TraceAssertionError(f"silent dtype changes: {detail}", violations)
