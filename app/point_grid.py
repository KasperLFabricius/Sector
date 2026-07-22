"""A single editable point grid (one table per point set) built on Tabulator.

Replaces the previous two-part layout (an ID-free ``st.data_editor`` beside a
read-only ID list). One grid now carries a frozen, non-editable ID column that
auto-numbers the complete points (matching the plot), a frozen header, freely
editable numeric cells and Excel-style block paste -- features ``st.data_editor``
cannot combine. It is a self-contained Streamlit Components v2 component: the
vendored Tabulator assets and Sector renderer under ``point_grid_frontend/`` are
passed as inline content, so the frozen desktop app needs no separately installed
component package and no frontend build step.

The grid keeps its own live state across reruns; it only re-seeds from ``df`` when
``data_version`` changes, so a Load/Clear/Add-void can refresh it without a plain
keystroke ever resetting or lagging the table.
"""

from __future__ import annotations

import math
from pathlib import Path
from weakref import WeakKeyDictionary

import pandas as pd
import streamlit as st
from streamlit.components.v2.get_bidi_component_manager import (
    get_bidi_component_manager,
)

_FRONTEND = Path(__file__).resolve().parent / "point_grid_frontend"


def _frontend_text(name: str) -> str:
    """Load a vendored frontend asset as inline CCv2 content."""
    return (_FRONTEND / name).read_text(encoding="utf-8")


_COMPONENT_HTML = _frontend_text("point_grid.html")
_COMPONENT_CSS = (
    _frontend_text("tabulator.min.css") + "\n" + _frontend_text("point_grid.css")
)
_COMPONENT_JS = (
    _frontend_text("tabulator.min.js") + "\n" + _frontend_text("point_grid.js")
)
_COMPONENT_RENDERERS = WeakKeyDictionary()


def _component(**kwargs):
    """Register and mount the grid in the active Streamlit runtime.

    AppTest creates isolated runtimes in one Python process. Registering only at
    module import would leave later runtimes without the definition when this
    module is already cached. The asset strings remain cached above; this small
    call makes the definition available to whichever runtime is mounting it.
    """
    manager = get_bidi_component_manager()
    renderer = _COMPONENT_RENDERERS.get(manager)
    if renderer is None:
        renderer = st.components.v2.component(
            "sector.point_grid_rich_v1",
            html=_COMPONENT_HTML,
            css=_COMPONENT_CSS,
            js=_COMPONENT_JS,
            isolate_styles=True,
        )
        _COMPONENT_RENDERERS[manager] = renderer
    return renderer(**kwargs)


def _normalise_specs(columns, column_specs=None) -> list[dict]:
    """Return strict, ordered frontend metadata for every persisted column."""
    cols = list(columns)
    supplied = {
        str(spec.get("field")): dict(spec)
        for spec in (column_specs or [])
        if isinstance(spec, dict) and spec.get("field") is not None
    }
    specs = []
    for column in cols:
        spec = supplied.get(column, {"field": column, "title": column,
                                     "type": "number"})
        spec["field"] = column
        spec.setdefault("title", column)
        spec.setdefault("type", "number")
        specs.append(spec)
    return specs


def _component_records(df: pd.DataFrame, columns, column_specs=None) -> list[dict]:
    """Return strict-JSON-safe rows for the component seed.

    Pandas keeps a numeric column's dtype when ``where(..., None)`` is used, so
    the apparent ``None`` values are coerced straight back to ``NaN``.  Streamlit
    then serialises that non-standard value into the component payload and the
    browser's JSON parser rejects it.  Convert cell-by-cell instead: every finite
    numeric value is retained and every blank or non-finite value becomes JSON
    ``null``.
    """
    cols = list(columns)
    specs = _normalise_specs(cols, column_specs)
    base = (df.reindex(columns=cols)
            if df is not None else pd.DataFrame(columns=cols))
    records = []
    for row in base.itertuples(index=False, name=None):
        record = {}
        for column, spec, value in zip(cols, specs, row):
            if spec["type"] == "number":
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    number = math.nan
                record[column] = number if math.isfinite(number) else None
            else:
                try:
                    blank = value is None or bool(pd.isna(value))
                except (TypeError, ValueError):
                    blank = True
                record[column] = "" if blank else str(value).strip()
        records.append(record)
    return records


def _rows_to_df(rows, columns, column_specs=None) -> pd.DataFrame:
    """The grid's returned rows as a typed DataFrame with exactly ``columns``.

    Numeric blanks become ``NaN``; text blanks become empty strings. A half-typed
    row or a void's blank separator therefore survives the round trip.
    """
    cols = list(columns)
    specs = _normalise_specs(cols, column_specs)
    if not rows:
        return pd.DataFrame({
            column: pd.Series(dtype=("float64" if spec["type"] == "number"
                                     else "object"))
            for column, spec in zip(cols, specs)
        })
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]
    for column, spec in zip(cols, specs):
        if spec["type"] == "number":
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")
        else:
            def _text(value):
                try:
                    blank = value is None or bool(pd.isna(value))
                except (TypeError, ValueError):
                    blank = True
                return "" if blank else str(value).strip()

            df[column] = df[column].map(_text).astype("object")
    return df


def _versioned_rows(value, data_version):
    """Return rows only when a component payload belongs to the current seed.

    The frontend includes its ``data_version`` in every value. A browser can briefly
    deliver the previous grid value while a Clear/Load reseed is in flight; rejecting
    that stale payload keeps the new base authoritative. Unversioned list payloads
    from the previous frontend are deliberately rejected because they cannot prove
    which seed they belong to. Saved projects contain base tables, not component
    payloads, so this does not affect project compatibility.
    """
    if not isinstance(value, dict):
        return None
    # Components v2 stores Sector's versioned row object under the single
    # ``payload`` state key. Continue accepting the former direct shape so a
    # stale Session State value from v1 is rejected/accepted by version rather
    # than causing a transition-time exception.
    nested = value.get("payload")
    if isinstance(nested, dict):
        value = nested
    if str(value.get("data_version")) != str(data_version):
        return None
    rows = value.get("rows")
    return rows if isinstance(rows, list) else None


def point_grid(df: pd.DataFrame, columns, *, key: str, id_start: int = 1,
               data_version: int = 0, label: str | None = None,
               column_specs=None, component_options=None) -> pd.DataFrame:
    """Render the editable grid for ``df`` and return the edited rows.

    Numeric-only geometry tables use the legacy auto-numbered display ID. Rich
    reinforcement tables pass ``column_specs`` plus persistent-ID/derived-size
    ``component_options``. Bump ``data_version`` to re-seed from ``df``.
    """
    cols = list(columns)
    specs = _normalise_specs(cols, column_specs)
    # NaN is not valid JSON, so send blanks as null; this is also the default the
    # component returns before the frontend first reports (and under AppTest, which
    # does not run the frontend) -- i.e. the seeded table flows straight through.
    records = _component_records(df, cols, specs)
    default = {"data_version": str(data_version), "rows": records}
    data = {
        "columns": cols,
        "column_specs": specs,
        "rows": records,
        "id_start": int(id_start),
        "data_version": str(data_version),
        "label": label or "Editable section points",
    }
    data.update(dict(component_options or {}))
    result = _component(
        key=key,
        data=data,
        default={"payload": default},
        on_payload_change=lambda: None,
        width="stretch",
        height="content",
    )
    value = result.get("payload") if hasattr(result, "get") else None
    rows = _versioned_rows(value, data_version)
    return _rows_to_df(records if rows is None else rows, cols, specs)
