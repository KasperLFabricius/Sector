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

import hashlib
import json
import math
from datetime import datetime, timezone

import pandas as pd

from sector import __version__ as sector_version
from sector.build_info import source_revision

FORMAT = "sector-project"
VERSION = 3   # v3: application/source provenance and canonical input hash

# The four point-table session-state keys (DataFrames, millimetres).
TABLE_KEYS = ["corners_base", "hole_base", "bars_base", "tendons_base"]

# Every scalar / string input that makes up a project. Missing keys are skipped on
# save, so an older or partial file still loads what it has.
SCALAR_KEYS = [
    # Quick Section builder settings (durable mirror keys; the builder writes the
    # generated points into the tables, which are saved separately).
    "qsv_shape", "qsv_b_mm", "qsv_h_mm", "qsv_bf_mm", "qsv_hf_mm", "qsv_bw_mm",
    "qsv_hw_mm", "qsv_wall_mm", "qsv_dia_mm", "qsv_ring_n", "qsv_ring_d",
    "qsv_ring_c_mm", "qsv_qs_rebar_mode", "qsv_qs_cover_to_edge",
    "qsv_bot_n", "qsv_bot_d", "qsv_bot_s",
    "qsv_top_n", "qsv_top_d", "qsv_top_s", "qsv_bot_c_mm", "qsv_top_c_mm",
    "qsv_bot_n2", "qsv_top_n2", "qsv_bot_layers", "qsv_top_layers",
    "qsv_layer_s", "qsv_bot_off_d", "qsv_top_off_d", "qsv_tnd_n",
    "qsv_tnd_a", "qsv_tnd_c_mm", "qsv_tnd_layers", "qsv_tnd_layer_s",
    # Concrete.
    "conc_preset", "conc_fck", "conc_gamma_c", "conc_k_tc", "conc_alpha_cc",
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
    "pl_case_id", "pl_case_type", "pl_case_source",
    "el_case_id", "el_case_type", "el_case_source",
    "pl_P", "pl_Mx", "pl_My", "el_long_P", "el_long_Mx", "el_long_My", "el_phi",
    "el_short_P", "el_short_Mx", "el_short_My",
    # Analysis & result settings.
    "mode", "v_min", "v_max", "v_inc", "pl_check_util",
    "pl_interaction",
    "sls_cw", "sls_phi", "sls_bond", "sls_code", "sls_member",
    "sls_wk_limit", "sls_conc_limit_pct", "sls_steel_limit_pct",
    "sls_pre_limit_pct", "sls_limit_source",
    # Shear (VRd,c without links, and the variable-strut VRd with links).
    "shear_on", "shear_method", "shear_axis", "shear_tension", "shear_V", "shear_bw",
    "shear_dlower",
    "shear_links", "shear_link_legs", "shear_link_dia", "shear_link_s", "shear_fywk",
    "shear_cot_min", "shear_cot_max",
    # Torsion (thin-walled tube, TRd). The stirrup is the shared shear_link_* one.
    "torsion_on", "torsion_method", "torsion_T", "torsion_tef", "torsion_nu_v",
    "torsion_cot_min", "torsion_cot_max",
    # Sub-tube subdivision for compound / T-sections (6.3.1(3)).
    "torsion_subdivide", "torsion_nsub",
    "torsion_sub_x0", "torsion_sub_y0", "torsion_sub_x1", "torsion_sub_y1",
    "torsion_sub_x2", "torsion_sub_y2", "torsion_sub_x3", "torsion_sub_y3",
    "torsion_sub_b0", "torsion_sub_h0", "torsion_sub_b1", "torsion_sub_h1",
    "torsion_sub_b2", "torsion_sub_h2", "torsion_sub_b3", "torsion_sub_h3",
    # Combined M-V-T interaction.
    "combined_on", "combined_method", "combined_mv_independent",
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


def _canonical_inputs(tables: dict, scalars: dict) -> dict:
    """Return the JSON-native input payload used by both save and hash checks."""
    return {
        "tables": {k: _table_to_obj(tables.get(k)) for k in TABLE_KEYS},
        "scalars": {k: _scalar(scalars[k]) for k in SCALAR_KEYS if k in scalars},
    }


def input_sha256(tables: dict, scalars: dict) -> str:
    """Hash the canonical calculation inputs, independent of save timestamps."""
    content = _canonical_inputs(tables, scalars)
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dump_project(tables: dict, scalars: dict, *, calculation=None,
                 app_version=None, revision=None) -> str:
    """Serialise the point tables and scalar inputs to a JSON project string.

    ``tables`` maps the table keys to DataFrames; ``scalars`` maps the input keys
    to their values. Unknown scalar keys are dropped so the file stays canonical.
    """
    content = _canonical_inputs(tables, scalars)
    digest = input_sha256(tables, scalars)
    revision = str(revision or source_revision())
    app_version = str(app_version or sector_version)
    payload = {
        "format": FORMAT,
        "version": VERSION,
        **content,
        "provenance": {
            "sector_version": app_version,
            "source_revision": revision,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_sha256": digest,
            "results_included": False,
        },
    }
    if calculation:
        record = {
            key: calculation.get(key)
            for key in (
                "performed_at_utc", "sector_version", "source_revision",
                "input_sha256",
            )
            if calculation.get(key) not in (None, "")
        }
        record["matches_saved_inputs"] = record.get("input_sha256") == digest
        payload["calculation"] = record
    return json.dumps(payload, indent=2)


def project_provenance(text: str) -> dict:
    """Read and verify provenance without changing the parse return contract."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("not valid JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Sector project file")
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return {
            "sector_version": None,
            "source_revision": None,
            "saved_at_utc": None,
            "input_sha256": None,
            "input_hash_valid": None,
            "results_included": False,
            "calculation": None,
        }
    raw_tables = data.get("tables") or {}
    raw_scalars = data.get("scalars") or {}
    if not isinstance(raw_tables, dict) or not isinstance(raw_scalars, dict):
        raise ValueError("malformed 'tables' or 'scalars' section")
    canonical = json.dumps(
        {"tables": raw_tables, "scalars": raw_scalars},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    recorded = provenance.get("input_sha256")
    calculation = (
        dict(data["calculation"])
        if isinstance(data.get("calculation"), dict) else None
    )
    if calculation is not None:
        calculation["matches_saved_inputs"] = (
            bool(calculation.get("input_sha256"))
            and calculation.get("input_sha256") == actual
        )
    return {
        "sector_version": provenance.get("sector_version"),
        "source_revision": provenance.get("source_revision"),
        "saved_at_utc": provenance.get("saved_at_utc"),
        "input_sha256": recorded,
        "input_hash_valid": bool(recorded) and recorded == actual,
        "results_included": bool(provenance.get("results_included", False)),
        "calculation": calculation,
    }


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
    # Files saved before the explicit EN 1992-1-1:2023 applicability selector have
    # no k_tc field. Migrate those deterministically to the general/other-case value
    # instead of letting an unrelated preset value already in session state leak
    # into the loaded calculation.
    if "2023" in str(scalars.get("conc_preset", "")):
        scalars.setdefault("conc_k_tc", 0.85)
    # The steel moduli are now entered in GPa; files written before that stored them
    # in MPa. A real modulus in GPa is at most a few hundred, so a value of 1000 or
    # more is unambiguously a legacy MPa figure -- rescale it so old projects load
    # correctly. (New files store GPa, well below the threshold, so re-loading them
    # is a no-op.)
    for key in ("mild_Es", "pre_Es"):
        val = scalars.get(key)
        if isinstance(val, (int, float)) and val >= 1000.0:
            scalars[key] = val / 1000.0
    # The axial force N is now tension-positive; files written before that (version
    # < 2) stored it compression-positive, so negate their axial values to preserve
    # the physical loads. Moments are unchanged.
    if data.get("version", 1) < 2:
        for key in ("pl_P", "el_long_P", "el_short_P"):
            val = scalars.get(key)
            if isinstance(val, (int, float)):
                scalars[key] = -val
    # Quick Section rebar rework (v0.42): the interleave diameters became numeric
    # (0 = off; previously "none" or a string diameter), and the single cover split
    # into a separate top and bottom cover.
    for key in ("qsv_bot_off_d", "qsv_top_off_d"):
        val = scalars.get(key)
        if isinstance(val, str):
            scalars[key] = 0.0 if val == "none" else float(val)
    old_cover = raw_scalars.get("qsv_cover_mm")      # single cover -> both faces
    if isinstance(old_cover, (int, float)):
        scalars.setdefault("qsv_bot_c_mm", float(old_cover))
        scalars.setdefault("qsv_top_c_mm", float(old_cover))
    # v0.48 merged the separate torsion stirrup (torsion_stirrup_dia/_s, torsion_fywk)
    # into the shared shear_link_* stirrup. Fold a deliberately-configured legacy
    # torsion stirrup into the shared keys, so a project that used torsion keeps its
    # stirrup. Conditions:
    #   * shear links are not active -- both shear_on and shear_links set means the
    #     shear stirrup is the real one and is kept (two stirrups cannot both survive);
    #     shear_links alone can be stale after shear_on was turned off;
    #   * the torsion stirrup was actually customised (differs from the app defaults)
    #     -- so a dormant default torsion stirrup never overwrites a custom shear one,
    #     and the migration also fires when the torsion check was toggled off before
    #     saving (its custom stirrup would otherwise be lost on re-enable).
    _shear_active = bool(raw_scalars.get("shear_on") and raw_scalars.get("shear_links"))
    _legacy_stirrup = (("torsion_stirrup_dia", "shear_link_dia", 10.0),
                       ("torsion_stirrup_s", "shear_link_s", 150.0),
                       ("torsion_fywk", "shear_fywk", 500.0))
    _customised = any(isinstance(raw_scalars.get(old), (int, float))
                      and raw_scalars[old] != dflt
                      for old, _new, dflt in _legacy_stirrup)
    if _customised and not _shear_active:
        for old, new, _dflt in _legacy_stirrup:
            val = raw_scalars.get(old)
            if isinstance(val, (int, float)):
                scalars[new] = float(val)
    return tables, scalars
