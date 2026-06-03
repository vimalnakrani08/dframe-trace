import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pandas as pd
from dframe_trace import traced, trace


@traced("load")
def load(_):
    return pd.DataFrame({"id": [1, 2, 3, 4], "amt": [10.0, 20.0, 30.0, 40.0]})


@traced("merge_meta")
def merge_meta(df):
    meta = pd.DataFrame({"id": [1, 2, 3], "region": ["x", "y", "z"]})
    # left join introduces nulls in 'region' for id=4 -- classic silent bug
    return df.merge(meta, on="id", how="left")


@traced("filter_positive")
def filter_positive(df):
    return df[df["amt"] > 15]  # drops rows


@traced("cast")
def cast(df):
    df = df.copy()
    df["id"] = df["id"].astype("float64")  # silent dtype shift
    return df


def test_pipeline_tracing():
    with trace() as t:
        df = load(None)
        df = merge_meta(df)
        df = filter_positive(df)
        df = cast(df)

    # the library pinpoints the bug without any manual prints
    assert t.where_null_introduced("region") == "merge_meta"
    lost = t.where_rows_lost()
    assert lost == [("filter_positive", -1)]

    diffs = [s.diff() for s in t.steps]
    assert "region" in diffs[1]["cols_added"]
    assert diffs[3]["dtype_changes"]["id"] == ("int64", "float64")

    print(t.report())


if __name__ == "__main__":
    test_pipeline_tracing()
    print("\nALL TESTS PASSED")
