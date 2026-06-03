import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from dframe_trace import trace, autopatch, guards


def build_pipeline():
    """Plain pandas. No decorators anywhere."""
    raw = pd.DataFrame({"id": [1, 2, 3, 4], "amt": [10.0, 20.0, 30.0, 40.0]})
    meta = pd.DataFrame({"id": [1, 2, 3], "region": ["x", "y", "z"]})
    df = raw.merge(meta, on="id", how="left")     # null in region for id=4
    df = df.astype({"id": "float64"})             # silent cast
    df = df[df["amt"] > 15]                        # NOTE: __getitem__, not patched
    df = df.dropna(subset=["region"])              # drops the null row
    return df


def test_autopatch_records_without_decorators():
    autopatch.install()
    try:
        with trace() as t:
            build_pipeline()
        names = [s.name for s in t.steps]
        # merge, astype, dropna all captured automatically
        assert "merge" in names
        assert "astype" in names
        assert "dropna" in names
        assert t.where_null_introduced("region") == "merge"
    finally:
        autopatch.uninstall()

    # after uninstall, plain pandas no longer records
    with trace() as t2:
        build_pipeline()
    assert len(t2.steps) == 0


def test_overhead_outside_trace_is_inert():
    autopatch.install()
    try:
        # no active trace -> calls work normally and record nothing
        df = pd.DataFrame({"a": [1, 2]}).rename(columns={"a": "b"})
        assert list(df.columns) == ["b"]
    finally:
        autopatch.uninstall()


def test_guards_raise_correctly():
    autopatch.install()
    try:
        with trace() as t:
            build_pipeline()
    finally:
        autopatch.uninstall()

    # null guard should fire on the merge step
    try:
        guards.assert_no_new_nulls(t)
        assert False, "expected TraceAssertionError"
    except guards.TraceAssertionError as e:
        assert any(v[1] == "region" for v in e.violations)

    # silent cast guard fires; allowing astype suppresses it
    try:
        guards.assert_no_silent_casts(t)
        assert False, "expected TraceAssertionError"
    except guards.TraceAssertionError:
        pass
    guards.assert_no_silent_casts(t, allow={"astype"})  # should NOT raise


if __name__ == "__main__":
    test_autopatch_records_without_decorators()
    test_overhead_outside_trace_is_inert()
    test_guards_raise_correctly()
    print("ALL AUTOPATCH + GUARD TESTS PASSED")
