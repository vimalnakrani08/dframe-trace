"""Polars integration tests.

These run only if polars is installed (skipped otherwise) so the suite passes
in any environment. Run locally with `pip install polars pytest` to verify the
polars backend against the real library.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

pl = pytest.importorskip("polars")

from dframe_trace import trace, autopatch, guards
from dframe_trace.backends import snapshot


def test_polars_eager_snapshot():
    df = pl.DataFrame({"id": [1, 2, 3], "region": ["x", None, "z"]})
    snap = snapshot(df)
    assert snap["rows"] == 3
    assert snap["nulls"]["region"] == 1
    assert snap["nulls"]["id"] == 0


def test_polars_lazyframe_skipped():
    lf = pl.LazyFrame({"a": [1, 2, 3]})
    assert snapshot(lf) is None  # lazy frames intentionally not snapshotted


def test_polars_autopatch_eager():
    autopatch.install()
    try:
        with trace() as t:
            raw = pl.DataFrame({"id": [1, 2, 3, 4], "amt": [10, 20, 30, 40]})
            meta = pl.DataFrame({"id": [1, 2, 3], "region": ["x", "y", "z"]})
            df = raw.join(meta, on="id", how="left")   # null in region for id=4
            df = df.drop_nulls(subset=["region"])       # drops that row
        names = [s.name for s in t.steps]
        assert "join" in names
        assert "drop_nulls" in names
        assert t.where_null_introduced("region") == "join"
    finally:
        autopatch.uninstall()


def test_polars_autopatch_lazy_collect():
    autopatch.install()
    try:
        with trace() as t:
            lf = pl.LazyFrame({"id": [1, 2, 3, 4], "amt": [10, 20, 30, 40]})
            out = lf.filter(pl.col("amt") > 15).collect()
        names = [s.name for s in t.steps]
        # lazy chain materializes at collect -> one recorded step
        assert "collect" in names
        assert out.height == 3
    finally:
        autopatch.uninstall()


def test_polars_guards():
    autopatch.install()
    try:
        with trace() as t:
            raw = pl.DataFrame({"id": [1, 2, 3, 4]})
            meta = pl.DataFrame({"id": [1, 2, 3], "region": ["x", "y", "z"]})
            raw.join(meta, on="id", how="left")
    finally:
        autopatch.uninstall()
    with pytest.raises(guards.TraceAssertionError):
        guards.assert_no_new_nulls(t)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
