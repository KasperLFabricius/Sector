"""A single editable point grid (one table per point set) built on Tabulator.

Replaces the previous two-part layout (an ID-free ``st.data_editor`` beside a
read-only ID list). One grid now carries a frozen, non-editable ID column that
auto-numbers the complete points (matching the plot), a frozen header, freely
editable numeric cells and Excel-style block paste -- features ``st.data_editor``
cannot combine. It is a self-contained Streamlit component: a static frontend
(vendored Tabulator, MIT) under ``point_grid_frontend/`` and this thin wrapper, so
there is no new Python dependency and nothing to build.

The grid keeps its own live state across reruns; it only re-seeds from ``df`` when
``data_version`` changes, so a Load/Clear/Add-void can refresh it without a plain
keystroke ever resetting or lagging the table.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit.components.v1 as components

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "point_grid_frontend")
_component = components.declare_component("sector_point_grid", path=_FRONTEND)


def _rows_to_df(rows, columns) -> pd.DataFrame:
    """The grid's returned rows as a numeric DataFrame with exactly ``columns``.

    Blank and non-numeric cells become ``NaN`` (the downstream point parsing skips
    them), so a half-typed row or a void's blank separator survives the round trip.
    """
    cols = list(columns)
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.astype("float64")


def _versioned_rows(value, data_version):
    """Return rows only when a component payload belongs to the current seed.

    The frontend includes its ``data_version`` in every value. A browser can briefly
    deliver the previous grid value while a Clear/Load reseed is in flight; rejecting
    that stale payload keeps the new base authoritative. Plain lists remain accepted
    for saved sessions and tests created before versioned payloads were introduced.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    if str(value.get("data_version")) != str(data_version):
        return None
    rows = value.get("rows")
    return rows if isinstance(rows, list) else None


def point_grid(df: pd.DataFrame, columns, *, key: str, id_start: int = 1,
               data_version: int = 0) -> pd.DataFrame:
    """Render the editable grid for ``df`` and return the edited rows.

    ``columns`` are the editable column names (``["x (mm)", "y (mm)"]`` or with an
    ``"area (mm2)"``). ``id_start`` offsets the auto-numbered ID column so each
    table continues the plot's numbering (bars from 1, tendons after the bars,
    etc.). Bump ``data_version`` to make the grid re-seed from ``df``.
    """
    cols = list(columns)
    base = df.reindex(columns=cols) if df is not None else pd.DataFrame(columns=cols)
    # NaN is not valid JSON, so send blanks as null; this is also the default the
    # component returns before the frontend first reports (and under AppTest, which
    # does not run the frontend) -- i.e. the seeded table flows straight through.
    records = base.where(pd.notnull(base), None).to_dict("records")
    default = {"data_version": str(data_version), "rows": records}
    value = _component(columns=cols, data=records, id_start=int(id_start),
                       data_version=str(data_version), key=key, default=default)
    rows = _versioned_rows(value, data_version)
    return _rows_to_df(records if rows is None else rows, cols)
