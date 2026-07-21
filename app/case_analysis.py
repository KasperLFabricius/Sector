"""Pure orchestration for running Sector's typed load-case tables.

The numerical calculation remains owned by ``sector_app.run_analysis``'s
single-case implementation.  This module maps canonical table rows onto that
stable input contract, invokes an injected single-case runner, and returns an
ordered result per named case.  Keeping the orchestration free of Streamlit makes
the rules for signs, skipped actions, acceptance flags and cache reuse directly
unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import load_cases


_PLASTIC_RESULT_KEYS = ("plastic", "shear", "torsion", "combined")
_ELASTIC_RESULT_KEYS = ("elastic",)


def _case_record(row: Mapping, key: str) -> dict:
    """Return one canonical, JSON-like row with native Python scalar types."""
    record = {
        load_cases.NAME: str(row.get(load_cases.NAME) or "").strip(),
        load_cases.DESCRIPTION: str(
            row.get(load_cases.DESCRIPTION) or ""
        ).strip(),
    }
    record.update({
        column: float(row[column])
        for column in load_cases.NUMERIC_COLUMNS[key]
    })
    record.update({
        column: bool(row[column])
        for column in load_cases.FLAG_COLUMNS[key]
    })
    return record


def _rows(value, key: str) -> list[dict]:
    frame = load_cases.active_table(value, key)
    return [_case_record(row, key) for row in frame.to_dict("records")]


def case_records(inp: Mapping, family: str) -> list[dict]:
    """Return canonical records for one solver family for presentation."""
    keys = {
        "plastic": load_cases.PLASTIC_TABLE_KEY,
        "elastic": load_cases.ELASTIC_TABLE_KEY,
    }
    if family not in keys:
        raise ValueError(f"unknown case family: {family}")
    key = keys[family]
    return _rows(inp.get(f"{family}_cases"), key)


def case_signature(record: Mapping, key: str) -> tuple:
    """Stable per-row signature used only after shared inputs have matched."""
    return tuple(record[column] for column in load_cases.TABLE_COLUMNS[key])


def plastic_bending_signature(record: Mapping) -> tuple:
    """Actions that affect the Plastic envelope/utilisation sub-result."""
    return tuple(
        float(record[column])
        for column in ("n_ed_kn", "mx_ed_knm", "my_ed_knm")
    )


def _metadata(record: Mapping) -> dict:
    return {
        "id": record[load_cases.NAME],
        "type": record[load_cases.DESCRIPTION],
        "source": "",
    }


def plastic_case_input(base: Mapping, record: Mapping) -> dict:
    """Map one Plastic table row onto the existing single-case input contract.

    N/M retain their signs. Shear and torsion are capacity magnitudes internally,
    while the signed source values remain in the case entry returned to callers.
    A zero VEd or TEd disables that check for this row, regardless of the global
    method toggle. Combined M-V-T is live only when both actions are non-zero.
    """
    out = dict(base)
    v_ed = float(record["v_ed_kn"])
    t_ed = float(record["t_ed_knm"])
    shear_live = bool(base.get("shear_on")) and abs(v_ed) > 0.0
    torsion_live = bool(base.get("torsion_on")) and abs(t_ed) > 0.0
    bending_live = str(base.get("mode") or "") in {"Plastic", "Both"}
    out.update(
        mode="Plastic" if bending_live else "Capacity",
        plastic_case=_metadata(record),
        P_pl=float(record["n_ed_kn"]),
        Mx_pl=float(record["mx_ed_knm"]),
        My_pl=float(record["my_ed_knm"]),
        shear_V=abs(v_ed),
        torsion_T=abs(t_ed),
        shear_requested=bool(base.get("shear_on")),
        torsion_requested=bool(base.get("torsion_on")),
        combined_requested=bool(base.get("combined_on")),
        shear_on=shear_live,
        torsion_on=torsion_live,
        combined_on=(
            bool(base.get("combined_on")) and shear_live and torsion_live
        ),
    )
    return out


def elastic_case_input(base: Mapping, record: Mapping) -> dict:
    """Map one Elastic row and its per-case acceptance selections."""
    out = dict(base)
    check_stress = bool(record["check_stress"])
    check_crack_width = bool(record["check_crack_width"])
    out.update(
        mode="Elastic",
        elastic_case=_metadata(record),
        check_stress=check_stress,
        check_crack_width=check_crack_width,
        P_el_l=float(record["n_long_ed_kn"]),
        Mx_el_l=float(record["mx_long_ed_knm"]),
        My_el_l=float(record["my_long_ed_knm"]),
        P_el_s=float(record["n_short_ed_kn"]),
        Mx_el_s=float(record["mx_short_ed_knm"]),
        My_el_s=float(record["my_short_ed_knm"]),
        sls_cw=check_crack_width,
        sls_conc_limit_pct=(
            float(base.get("sls_conc_limit_pct", 0.0)) if check_stress else 0.0
        ),
        sls_steel_limit_pct=(
            float(base.get("sls_steel_limit_pct", 0.0)) if check_stress else 0.0
        ),
        sls_pre_limit_pct=(
            float(base.get("sls_pre_limit_pct", 0.0)) if check_stress else 0.0
        ),
        shear_on=False,
        torsion_on=False,
        combined_on=False,
    )
    return out


def _reuse_by_name(entries: Sequence[Mapping] | None) -> dict[str, Mapping]:
    return {
        str(entry.get("name") or ""): entry
        for entry in (entries or [])
        if isinstance(entry, Mapping) and entry.get("name")
    }


def _entry(record: dict, key: str, result: dict, *, evaluated: bool,
           reused: bool) -> dict:
    entry = {
        "name": record[load_cases.NAME],
        "description": record[load_cases.DESCRIPTION],
        "actions": dict(record),
        "signature": case_signature(record, key),
        "evaluated": bool(evaluated),
        "reused": bool(reused),
        "results": result,
    }
    if key == load_cases.PLASTIC_TABLE_KEY:
        entry["bending_signature"] = plastic_bending_signature(record)
    return entry


def _first_results(entries: Sequence[Mapping], keys: Sequence[str]) -> dict:
    """Compatibility view for the existing one-case UI and PDF path."""
    if not entries:
        return {}
    result = entries[0].get("results") or {}
    return {key: result[key] for key in keys if key in result}


def validation_errors(inp: Mapping) -> list[str]:
    """Return table/name errors for the analyses enabled in ``inp``."""
    mode = str(inp.get("mode") or "")
    plastic_required = (
        mode in {"Plastic", "Both"}
        or bool(inp.get("shear_on"))
        or bool(inp.get("torsion_on"))
        or bool(inp.get("combined_on"))
    )
    elastic_required = mode in {"Elastic", "Both"}
    return load_cases.validation_errors(
        inp.get("plastic_cases"),
        inp.get("elastic_cases"),
        require_plastic=plastic_required,
        require_elastic=elastic_required,
    )


def run_case_tables(
    inp: Mapping,
    runner: Callable[..., dict],
    *,
    reuse_plastic: Sequence[Mapping] | None = None,
    reuse_plastic_bending: Sequence[Mapping] | None = None,
    reuse_elastic: Sequence[Mapping] | None = None,
) -> dict:
    """Run every active canonical case through ``runner`` in table order.

    Reuse entries are trusted only for the row signature. The caller must pass
    them solely when the corresponding shared geometry/material/method signature
    is unchanged. This separation lets a future table edit recompute only changed
    rows without ever reusing results across changed engineering context.
    """
    plastic_table = inp.get("plastic_cases")
    elastic_table = inp.get("elastic_cases")
    mode = str(inp.get("mode") or "")
    plastic_required = (
        mode in {"Plastic", "Both"}
        or bool(inp.get("shear_on"))
        or bool(inp.get("torsion_on"))
        or bool(inp.get("combined_on"))
    )
    elastic_required = mode in {"Elastic", "Both"}
    errors = validation_errors(inp)
    if errors:
        raise ValueError("; ".join(errors))

    plastic_rows = _rows(plastic_table, load_cases.PLASTIC_TABLE_KEY)
    elastic_rows = _rows(elastic_table, load_cases.ELASTIC_TABLE_KEY)
    cached_plastic = _reuse_by_name(reuse_plastic)
    cached_plastic_bending = _reuse_by_name(reuse_plastic_bending)
    cached_elastic = _reuse_by_name(reuse_elastic)
    out = {}

    plastic_entries = []
    if plastic_required:
        bending_live = mode in {"Plastic", "Both"}
        for record in plastic_rows:
            signature = case_signature(record, load_cases.PLASTIC_TABLE_KEY)
            cached = cached_plastic.get(record[load_cases.NAME])
            if cached is not None and tuple(cached.get("signature") or ()) == signature:
                plastic_entries.append(
                    _entry(
                        record,
                        load_cases.PLASTIC_TABLE_KEY,
                        cached.get("results") or {},
                        evaluated=bool(cached.get("evaluated")),
                        reused=True,
                    )
                )
                continue
            case_inp = plastic_case_input(inp, record)
            evaluated = (
                bending_live
                or bool(case_inp["shear_on"])
                or bool(case_inp["torsion_on"])
            )
            previous = cached_plastic_bending.get(record[load_cases.NAME])
            previous_plastic = None
            if (
                bending_live
                and previous is not None
                and tuple(previous.get("bending_signature") or ())
                == plastic_bending_signature(record)
            ):
                previous_plastic = (
                    (previous.get("results") or {}).get("plastic")
                )
            result = (
                runner(case_inp, reuse_plastic=previous_plastic)
                if evaluated else {}
            )
            plastic_entries.append(
                _entry(
                    record,
                    load_cases.PLASTIC_TABLE_KEY,
                    result,
                    evaluated=evaluated,
                    reused=False,
                )
            )
        out["plastic_cases"] = plastic_entries
        out.update(_first_results(plastic_entries, _PLASTIC_RESULT_KEYS))

    elastic_entries = []
    if elastic_required:
        for record in elastic_rows:
            signature = case_signature(record, load_cases.ELASTIC_TABLE_KEY)
            cached = cached_elastic.get(record[load_cases.NAME])
            if cached is not None and tuple(cached.get("signature") or ()) == signature:
                elastic_entries.append(
                    _entry(
                        record,
                        load_cases.ELASTIC_TABLE_KEY,
                        cached.get("results") or {},
                        evaluated=True,
                        reused=True,
                    )
                )
                continue
            result = runner(elastic_case_input(inp, record))
            elastic_entries.append(
                _entry(
                    record,
                    load_cases.ELASTIC_TABLE_KEY,
                    result,
                    evaluated=True,
                    reused=False,
                )
            )
        out["elastic_cases"] = elastic_entries
        out.update(_first_results(elastic_entries, _ELASTIC_RESULT_KEYS))

    return out
