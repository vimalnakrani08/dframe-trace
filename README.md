# dframe-trace

**Find out where your data pipeline silently broke — without writing a single rule.**

When you process data in pandas or polars, each step quietly reshapes it: a join
introduces blank values, a filter drops rows you didn't expect, a cast turns
whole numbers into decimals. These bugs don't crash your program — they just
hand you *wrong answers*, often noticed far too late.

The usual fix is sprinkling `print(df.shape)` between every step and squinting at
the output. `dframe-trace` automates that. Turn it on with one line, run your normal
code, then ask questions afterward:

```python
t.where_null_introduced("region")   # -> "merge_meta"   (the step that did it)
t.where_rows_lost()                 # -> [("filter", -1)]
```

No schemas, no rules, no upfront declarations. Run your code, then interrogate
what happened.

---

## Table of contents
- [How it's different from Great Expectations / Pandera](#how-its-different)
- [Install](#install)
- [Quick start](#quick-start)
- [Frictionless mode (no decorators)](#frictionless-mode-no-decorators)
- [Use it as a CI gate](#use-it-as-a-ci-gate)
- [Works with polars too](#works-with-polars-too)
- [API reference](#api-reference)
- [Limitations](#limitations-read-before-relying-on-it)
- [Requirements](#requirements)
- [Contributing & license](#contributing)

---

## How it's different

The Python data-validation space is crowded, so here's where `dframe-trace` fits.

**Validation tools (Great Expectations, Pandera, Hamilton)** check your data
against rules *you write in advance*: "this column must never be null", "row
count must stay above 1000". They're excellent, mature, and the right choice
when you know your expectations.

**`dframe-trace` is the opposite philosophy: zero rules.** You declare nothing. It
records what *every* step did to your data, and you ask after the fact where
something changed. It's a debugging/observability tool, not a validation
framework — closer to a profiler that tracks data shape across a whole pipeline
than to a schema checker.

Use Pandera/GE when you know what "correct" looks like and want to enforce it.
Use `dframe-trace` when something is already wrong and you need to find *which step*
did it — or when you want a cheap always-on record of how data flows through a
script.

The two are complementary; nothing stops you using both.

## Install

```bash
pip install dframe-trace
```

`dframe-trace` itself has **no required dependencies**. You bring your own pandas
and/or polars.

## Quick start

Decorate each pipeline step, run inside a `trace()` block, then interrogate it:

```python
from dframe_trace import traced, trace

@traced("merge_meta")
def merge_meta(df):
    return df.merge(meta, on="id", how="left")   # silently introduces nulls

@traced("filter")
def filter_rows(df):
    return df[df.amt > 15]                         # silently drops rows

with trace() as t:
    df = load(None)
    df = merge_meta(df)
    df = filter_rows(df)

print(t.where_null_introduced("region"))   # -> "merge_meta"
print(t.where_rows_lost())                 # -> [("filter", -1)]
print(t.report())
```

`t.report()` prints a readable step-by-step diff:

```
dframe-trace report
============================================================
[0] load  (0.5 ms)
    start: 4 rows, 2 cols
[1] merge_meta  (1.4 ms)
    +cols: ['region']
    nulls region: 0 -> 1  [WARN]
[2] filter  (0.4 ms)
    rows: -1
```

## Frictionless mode (no decorators)

Don't want to touch your functions? Patch pandas/polars once and write ordinary
code — every relevant call inside a `trace()` block is recorded automatically:

```python
import pandas as pd
from dframe_trace import trace, autopatch

autopatch.install()   # one line at the top of your script

with trace() as t:
    df = raw.merge(meta, on="id", how="left")   # recorded automatically
    df = df.astype({"id": "float64"})            # recorded automatically
    df = df.dropna(subset=["region"])            # recorded automatically

print(t.report())
print(t.where_null_introduced("region"))   # -> "merge"

autopatch.uninstall()   # optional: restore original methods
```

`autopatch` wraps the methods that most often cause silent bugs. Outside an
active `trace()` block the overhead is a single `is None` check, so it's safe to
leave installed.

## Use it as a CI gate

Turn a trace into a build-failing assertion in your test suite:

```python
from dframe_trace import trace, guards

with trace() as t:
    run_pipeline()

guards.assert_no_new_nulls(t)                    # raises if a step added nulls
guards.assert_no_row_loss(t, allow={"filter"})   # allow expected row drops
guards.assert_no_silent_casts(t, allow={"astype"})
```

Each guard raises `TraceAssertionError` with a structured `.violations` list, so
failures are precise: *"merge introduced 2 null(s) in 'region'"*.

## Works with polars too

`dframe-trace` is backend-agnostic. `autopatch.install()` patches whichever of
pandas / polars is installed:

```python
import polars as pl
from dframe_trace import trace, autopatch

autopatch.install()

with trace() as t:
    df = raw.join(meta, on="id", how="left")   # eager: recorded automatically
    df = df.drop_nulls(subset=["region"])

    out = (lf.filter(pl.col("amt") > 15)        # lazy: the chain builds a plan…
             .collect())                         # …and is recorded at .collect()

print(t.where_null_introduced("region"))   # -> "join"
```

Eager polars `DataFrame` methods (`join`, `drop_nulls`, `fill_null`, `cast`,
`filter`, `sort`, `unique`, `with_columns`, `select`, …) are traced like pandas.
For **lazy** `LazyFrame` pipelines, intermediate operations only build a query
plan and can't be snapshotted cheaply, so tracing happens at the `.collect()`
boundary where the plan materializes into a real frame.

## API reference

**`trace()`** — context manager. Opens a recording session; yields a `Trace`.

**`@traced(name=None, note="")`** — decorator for a function whose first argument
is a frame and which returns a frame. Records a before/after snapshot under
`name` (defaults to the function name).

**`autopatch.install(pandas=True, polars=True)`** — monkeypatch DataFrame methods
so calls record automatically. Idempotent; safe when a library is absent.
**`autopatch.uninstall()`** restores originals. **`autopatch.is_installed()`**
returns the current state.

**`Trace` methods:**
- `where_null_introduced(column)` → name of the first step that added nulls to
  `column`, or `None`.
- `where_rows_lost()` → list of `(step_name, negative_delta)` for steps that
  dropped rows.
- `report()` → human-readable string of every step and what changed.
- `steps` → the raw list of `Step` objects; each has `.diff()` returning a dict
  of `rows_delta`, `cols_added`, `cols_dropped`, `dtype_changes`, `null_changes`,
  `mem_delta_bytes`.

**Guards (each raises `guards.TraceAssertionError` on violation):**
- `assert_no_new_nulls(trace, columns=None)`
- `assert_no_row_loss(trace, allow=None)`
- `assert_no_silent_casts(trace, allow=None)`

A snapshot is structural only — row count, column names, dtypes, per-column null
counts, and estimated memory. **No row values are ever copied or stored**, which
is why it's cheap enough to leave on.

## Limitations (read before relying on it)

- **Boolean-mask filtering (`df[df.x > 0]`) is not auto-traced.** That uses
  `__getitem__`, an operator we deliberately don't patch (too broad, too risky).
  The row loss still appears in the *next* recorded step's row delta, just not
  attributed to the filter itself. For precise attribution, wrap that function
  with `@traced`.
- **`groupby` is not yet traced.** It returns a GroupBy object rather than a
  DataFrame; tracing its terminal `.agg`/`.sum` is on the roadmap.
- **polars support is newer than the pandas support.** The pandas path is
  thoroughly tested; please run the polars test suite against your polars version
  (see below) and report issues.
- This is a young project. It's a debugging aid, not a guarantee of correctness.

## Requirements

- Python 3.9+
- pandas and/or polars (whichever you use; neither is installed by `dframe-trace`)

To run the tests locally:

```bash
pip install pandas polars pytest
pip install -e .
python -m pytest tests/ -v
```

The polars tests auto-skip if polars isn't installed.

## Roadmap (good first issues for contributors)
- `groupby` terminal-method tracing
- HTML / Mermaid lineage diagram export from a `Trace`
- More guards (e.g. assert_no_schema_change)

## Contributing

Issues and pull requests welcome. Fork the repo, make your change with a test,
and open a PR. Good first issues are tagged in the roadmap above.

## License

MIT. See the LICENSE file.
