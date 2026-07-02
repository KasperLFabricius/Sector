"""Serialise the full input set to a project file and read it back (Save / Load).

A project file is JSON: the four point tables (concrete corners, voids, bars and
tendons, all in millimetres) plus the material, load and analysis-setting inputs.
The geometry tables are the source of truth, so saving them and the scalar inputs
captures everything needed to reproduce a section. Only the *inputs* are stored --
the results are recomputed on load.

The functions here are pure (no Streamlit), so the round trip is unit-tested
directly; the app wires the download / upload widgets to them.
"""

from __future__ import annotations

import json
import math

import pandas as pd

FORMAT = "sector-project"
VERSION = 1

# The four point-table session-state keys (DataFrames, millimetres).
TABLE_KEYS = ["corners_base", "hole_base", "bars_base", "tendons_base"]

# Every scalar / string input that makes up a project. Missing keys are skipped on
# save, so an older or partial file still loads what it has.
SCALAR_KEYS = [
    # Quick Section builder settings (durable mirror keys; the builder writes the
    # generated points into the tables, which are saved separately).
    "qsv_shape", "qsv_b_mm", "qsv_h_mm", "qsv_bf_mm", "qsv_hf_mm", "qsv_bw_mm",
    "qsv_hw_mm", "qsv_wall_mm", "qsv_dia_mm", "qsv_ring_n", "qsv_ring_d",
    "qsv_ring_c_mm", "qsv_qs_rebar_mode", "qsv_bot_n", "qsv_bot_d", "qsv_bot_s",
    "qsv_top_n", "qsv_top_d", "qsv_top_s", "qsv_bot_layers", "qsv_top_layers",
    "qsv_layer_s", "qsv_cover_mm", "qsv_tnd_n",
    "qsv_tnd_a", "qsv_tnd_c_mm", "qsv_tnd_layers", "qsv_tnd_layer_s",
    # Concrete.
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_alpha_cc",
    "conc_eps_c2", "conc_eps_cu2", "conc_n", "conc_Ec", "sls_fctm",
    # Mild reinforcement.
    "mild_preset", "mild_active_comp", "mild_fytk", "mild_fyck", "mild_futk",
    "mild_eut", "mild_gamma_y", "mild_gamma_u", "mild_gamma_E", "mild_k",
    "mild_ey0t", "mild_ey0c", "mild_Es",
    # Prestressing steel.
    "pre_preset", "pre_IS", "pre_fytk", "pre_futk", "pre_eut",
    "pre_gamma_y", "pre_gamma_u", "pre_gamma_E", "pre_k", "pre_ey0t", "pre_Es",
    # Loads. The modular ratios n_l/n_s are derived from Ec, Es, Ep and the creep
    # coefficient (el_phi), so they are not persisted -- they follow from the moduli.
    "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My", "el_phi",
    "el_short_P", "el_short_Mx", "el_short_My",
    # Analysis & result settings.
    "mode", "v_min", "v_max", "v_inc", "pl_check_util",
    "sls_cw", "sls_phi", "sls_bond", "sls_code", "sls_member",
    "label_scale", "label_min_gap",
    # Report metadata.
    "rep_proj_no", "rep_proj_name", "rep_section", "rep_rev", "rep_author",
    "rep_checker", "rep_approver", "rep_comments",
]

# A preset prefills its fields only when the selection *changes*; on load we set
# each change-marker to the loaded preset so the saved field values are kept.
PREV_MARKERS = {"conc_prev": "conc_preset", "mild_prev": "mild_preset",
                "pre_prev": "pre_preset"}


def _scalar(value):
    """Coerce a value to a JSON-native scalar (handle numpy / pandas types)."""
    if hasattr(value, "item"):           # numpy / pandas scalar
        return value.item()
    return value


def _cell(v):
    """A cell as a finite float, or ``None`` for a blank / non-numeric value.

    The point editors are paste-friendly, so a cell can momentarily hold a stray
    string; serialise that as a blank (the analysis skips it) rather than raising.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _table_to_obj(df) -> dict:
    """A DataFrame as ``{columns, rows}`` with blanks / stray cells stored as null."""
    if df is None:
        return {"columns": [], "rows": []}
    cols = [str(c) for c in df.columns]
    rows = [[_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]
    return {"columns": cols, "rows": rows}


def _obj_to_table(obj) -> pd.DataFrame:
    """Rebuild a numeric (``float64``) DataFrame from ``{columns, rows}``.

    Raises :class:`ValueError` on a malformed table object (not a ``{columns,
    rows}`` mapping) so the caller can report it rather than crash on an
    ``AttributeError``.
    """
    if not isinstance(obj, dict):
        raise ValueError("table entry is not a {columns, rows} object")
    cols = list(obj.get("columns", []))
    rows = obj.get("rows", []) or []
    try:
        df = pd.DataFrame(rows, columns=cols)
    except (ValueError, TypeError) as exc:      # ragged / non-tabular rows
        raise ValueError("table rows are not tabular") from exc
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.astype("float64") if cols else df


def dump_project(tables: dict, scalars: dict) -> str:
    """Serialise the point tables and scalar inputs to a JSON project string.

    ``tables`` maps the table keys to DataFrames; ``scalars`` maps the input keys
    to their values. Unknown scalar keys are dropped so the file stays canonical.
    """
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "tables": {k: _table_to_obj(tables.get(k)) for k in TABLE_KEYS},
        "scalars": {k: _scalar(scalars[k]) for k in SCALAR_KEYS if k in scalars},
    }
    return json.dumps(payload, indent=2)


def parse_project(text: str):
    """Read a project string into ``(tables, scalars)``.

    Raises :class:`ValueError` if the text is not a Sector project file (wrong
    format tag or unparseable JSON), so the caller can show a friendly message.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Sector project file")
    raw_tables = data.get("tables") or {}
    raw_scalars = data.get("scalars") or {}
    if not isinstance(raw_tables, dict) or not isinstance(raw_scalars, dict):
        raise ValueError("malformed 'tables' or 'scalars' section")
    tables = {k: _obj_to_table(raw_tables[k]) for k in TABLE_KEYS if k in raw_tables}
    scalars = {k: v for k, v in raw_scalars.items() if k in SCALAR_KEYS}
    return tables, scalars
