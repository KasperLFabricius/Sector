import dataclasses
import math

import pandas as pd
import pytest

from app import fatigue_inputs, load_cases, reinforcement_table
from app import table_field_definitions as fields


def test_registry_covers_all_seven_editable_tables_in_stable_order():
    assert fields.TABLE_KEYS == (
        "corners_base",
        "hole_base",
        "bars_base",
        "tendons_base",
        load_cases.PLASTIC_TABLE_KEY,
        load_cases.ELASTIC_TABLE_KEY,
        fatigue_inputs.SPECTRUM_TABLE_KEY,
    )
    expected_columns = {
        "corners_base": ("x (mm)", "y (mm)"),
        "hole_base": ("x (mm)", "y (mm)"),
        "bars_base": tuple(reinforcement_table.COLUMNS),
        "tendons_base": tuple(reinforcement_table.COLUMNS),
        load_cases.PLASTIC_TABLE_KEY: load_cases.PLASTIC_COLUMNS,
        load_cases.ELASTIC_TABLE_KEY: load_cases.ELASTIC_COLUMNS,
        fatigue_inputs.SPECTRUM_TABLE_KEY: fatigue_inputs.SPECTRUM_COLUMNS,
    }

    assert tuple(fields.TABLE_FIELD_DEFINITIONS) == fields.TABLE_KEYS
    for table_key, expected in expected_columns.items():
        definitions = fields.table_fields(table_key)
        assert tuple(item.key for item in definitions) == expected
        assert len(fields.field_map(table_key)) == len(expected)
        for item in definitions:
            assert isinstance(item, fields.FieldDefinition)
            assert all(
                str(getattr(item, attribute)).strip()
                for attribute in (
                    "key",
                    "label",
                    "help",
                    "math_symbol",
                    "unit",
                    "definition",
                    "sign",
                    "source",
                )
            )
            assert "$" not in item.label and "\\" not in item.label
            assert "$" not in item.help and "\\" not in item.help
            unit_math = fields.latex_unit(item.unit)
            assert "$" not in unit_math
            assert "^2" not in unit_math
            assert fields.input_rule(item)


def test_field_definitions_are_frozen_slotted_and_encode_blank_semantics():
    axial = fields.field_definition(load_cases.PLASTIC_TABLE_KEY, "n_ed_kn")
    case_name = fields.field_definition(load_cases.PLASTIC_TABLE_KEY, "name")
    cycles = fields.field_definition(fatigue_inputs.SPECTRUM_TABLE_KEY, "cycles")
    bar_area = fields.field_definition("bars_base", reinforcement_table.AREA)

    assert axial.blank is fields.BlankPolicy.ZERO
    assert case_name.blank is fields.BlankPolicy.REQUIRED
    assert cycles.blank is fields.BlankPolicy.REQUIRED
    assert bar_area.blank is fields.BlankPolicy.NULL
    assert axial.math_symbol == "N_{Ed}"
    assert hasattr(axial, "__slots__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        axial.label = "changed"

    assert fields.input_rule(axial) == "Blank = 0"
    assert fields.input_rule(case_name) == "Required"
    assert fields.input_rule(bar_area) == "Blank = not provided"
    assert fields.latex_unit("mm^2") == r"\mathrm{mm}^{2}"
    with pytest.raises(ValueError, match="unsupported editable-table unit"):
        fields.latex_unit("unknown")


@pytest.mark.parametrize(
    ("table_key", "prefix"),
    (("bars_base", "R"), ("tendons_base", "P")),
)
def test_reinforcement_id_blank_rule_matches_monotonic_allocator(
    table_key,
    prefix,
):
    identity = fields.field_definition(table_key, reinforcement_table.ELEMENT_ID)

    assert identity.default == (
        f"next {prefix} number above the highest retained suffix"
    )
    assert "lowest unused" not in fields.input_rule(identity).casefold()


@pytest.mark.parametrize(
    ("entered", "expected"),
    [
        ("1.25", 1.25),
        ("1,25", 1.25),
        ("-.5", -0.5),
        ("+,5e+2", 50.0),
        ("  -12,75E-1  ", -1.275),
        (3, 3.0),
    ],
)
def test_decimal_parser_accepts_one_dot_or_comma_with_sign_and_exponent(
    entered, expected
):
    assert fields.parse_decimal(entered) == pytest.approx(expected)


@pytest.mark.parametrize(
    "entered",
    [
        True,
        False,
        "1,234.5",
        "1.234,5",
        "1,2,3",
        "1 000",
        "1_000",
        "--1",
        "1e",
        "NaN",
        "inf",
        math.inf,
        math.nan,
        [],
    ],
)
def test_decimal_parser_rejects_ambiguous_boolean_and_nonfinite_values(entered):
    with pytest.raises(fields.DecimalParseError):
        fields.parse_decimal(entered)


def test_decimal_parser_applies_explicit_numeric_blank_policies():
    assert fields.parse_decimal("", blank=fields.BlankPolicy.ZERO) == 0.0
    assert fields.parse_decimal(None, blank=fields.BlankPolicy.NULL) is None
    assert fields.parse_decimal(
        "", blank=fields.BlankPolicy.DEFAULT, default=2.5
    ) == 2.5
    with pytest.raises(fields.DecimalParseError, match="required"):
        fields.parse_decimal(" ")


def test_load_case_decimal_comma_blank_and_malformed_ledger_lifecycle():
    table = load_cases.normalise_table(
        [{
            "name": "E1",
            "n_long_ed_kn": "-12,75",
            "mx_long_ed_knm": "bad decimal",
            "my_long_ed_knm": "",
        }],
        load_cases.ELASTIC_TABLE_KEY,
    )

    assert table.loc[0, "n_long_ed_kn"] == pytest.approx(-12.75)
    assert table.loc[0, "my_long_ed_knm"] == 0.0
    assert fields.is_invalid_decimal_sentinel(table.loc[0, "mx_long_ed_knm"])
    assert fields.decimal_issue_ledger(table.attrs) == {
        (0, "mx_long_ed_knm"): "bad decimal"
    }
    repeated = load_cases.normalise_table(table, load_cases.ELASTIC_TABLE_KEY)
    assert fields.is_invalid_decimal_sentinel(
        repeated.loc[0, "mx_long_ed_knm"]
    )
    with pytest.raises(ValueError, match="mx_long_ed_knm must be a finite"):
        load_cases.table_records(repeated, load_cases.ELASTIC_TABLE_KEY)

    repeated.loc[0, "mx_long_ed_knm"] = math.nan
    cleared = load_cases.normalise_table(
        repeated, load_cases.ELASTIC_TABLE_KEY
    )
    assert cleared.loc[0, "mx_long_ed_knm"] == 0.0
    assert fields.decimal_issue_ledger(cleared.attrs) == {}
    assert load_cases.table_records(
        cleared, load_cases.ELASTIC_TABLE_KEY
    )[0]["mx_long_ed_knm"] == 0.0


def test_load_editor_projection_preserves_decimal_text_and_reindexes_issues():
    canonical = load_cases.normalise_table(
        [
            {"name": "A", "n_ed_kn": "bad first"},
            {"name": "B", "n_ed_kn": "1,25", "mx_ed_knm": "bad second"},
        ],
        load_cases.PLASTIC_TABLE_KEY,
    )
    editor = load_cases.editor_table(canonical, load_cases.PLASTIC_TABLE_KEY)

    assert editor.loc[0, "n_ed_kn"] == "bad first"
    assert editor.loc[1, "n_ed_kn"] == "1.25"
    assert editor.loc[1, "mx_ed_knm"] == "bad second"
    reordered = editor.iloc[[1]].reset_index(drop=True)
    reparsed = load_cases.normalise_table(
        reordered, load_cases.PLASTIC_TABLE_KEY
    )
    assert reparsed.loc[0, "n_ed_kn"] == pytest.approx(1.25)
    assert fields.decimal_issue_ledger(reparsed.attrs) == {
        (0, "mx_ed_knm"): "bad second"
    }


def test_blank_load_actions_preserve_named_row_and_boolean_is_malformed():
    sparse = load_cases.normalise_table(
        [{"name": "P1", "n_ed_kn": None, "mx_ed_knm": " "}],
        load_cases.PLASTIC_TABLE_KEY,
    )
    assert len(load_cases.active_table(sparse, load_cases.PLASTIC_TABLE_KEY)) == 1
    assert all(sparse.loc[0, column] == 0.0 for column in load_cases.PLASTIC_NUMERIC)

    malformed = load_cases.normalise_table(
        [{"name": "P2", "n_ed_kn": True}],
        load_cases.PLASTIC_TABLE_KEY,
    )
    assert load_cases.validation_errors(
        malformed, load_cases.empty_table(load_cases.ELASTIC_TABLE_KEY)
    ) == ["Plastic row 1: n_ed_kn must be a finite number"]


def test_fatigue_required_cycles_and_zero_action_policies_are_distinct():
    table = fatigue_inputs.normalise_spectrum_table(
        [
            {},
            {
                "spectrum": "Traffic",
                "name": "Bin 1",
                "cycles": "2,5e5",
                "n_long_ed_kn": "",
                "mx_short_ed_knm": "1,125",
            },
            {"spectrum": "Traffic", "name": "Bin 2", "cycles": ""},
        ]
    )
    active = fatigue_inputs.active_spectrum_table(table)

    assert len(active) == 2
    assert active.loc[0, "cycles"] == pytest.approx(250000.0)
    assert active.loc[0, "n_long_ed_kn"] == 0.0
    assert active.loc[0, "mx_short_ed_knm"] == pytest.approx(1.125)
    assert fatigue_inputs.spectrum_errors(active) == [
        "Fatigue row 2: cycles is required"
    ]
    with pytest.raises(ValueError, match="cycles must be finite"):
        fatigue_inputs.spectrum_records(active)


def test_fatigue_malformed_action_survives_revalidation_then_clears_to_zero():
    table = fatigue_inputs.normalise_spectrum_table(
        [{
            "spectrum": "Traffic",
            "name": "Bin 1",
            "cycles": 10,
            "n_short_ed_kn": "not a number",
        }]
    )
    repeated = fatigue_inputs.normalise_spectrum_table(table)
    assert fields.decimal_issue_ledger(repeated.attrs) == {
        (0, "n_short_ed_kn"): "not a number"
    }
    assert fatigue_inputs.spectrum_errors(repeated) == [
        "Fatigue row 1: n_short_ed_kn must be a finite number"
    ]

    repeated.loc[0, "n_short_ed_kn"] = pd.NA
    cleared = fatigue_inputs.normalise_spectrum_table(repeated)
    assert cleared.loc[0, "n_short_ed_kn"] == 0.0
    assert fields.decimal_issue_ledger(cleared.attrs) == {}


def test_fatigue_editor_projection_keeps_cycles_and_actions_as_raw_text():
    canonical = fatigue_inputs.normalise_spectrum_table(
        [{
            "spectrum": "Traffic",
            "name": "Bin 1",
            "cycles": "2,5e5",
            "n_short_ed_kn": "12abc",
        }]
    )
    editor = fatigue_inputs.editor_spectrum_table(canonical)

    assert editor.loc[0, "cycles"] == "250000.0"
    assert editor.loc[0, "n_short_ed_kn"] == "12abc"
    editor.loc[0, "n_short_ed_kn"] = ""
    reparsed = fatigue_inputs.normalise_spectrum_table(editor)
    assert reparsed.loc[0, "n_short_ed_kn"] == 0.0
    assert fields.decimal_issue_ledger(reparsed.attrs) == {}


def test_fatigue_allocator_ignores_stale_counter_and_reserves_assignments():
    raw = {
        "version": fatigue_inputs.VERSION,
        "next_id": 999,
        "items": [
            {**fatigue_inputs.default_entry(), "id": "F1"},
            {**fatigue_inputs.default_entry(), "id": "F3"},
        ],
    }

    canonical = fatigue_inputs.normalise_catalog(raw)
    assert canonical["next_id"] == 2
    canonical, reused = fatigue_inputs.add_entry(canonical)
    assert reused == "F2"

    without_f2 = fatigue_inputs.delete_entry(canonical, "F2")
    reserved, new_id = fatigue_inputs.add_entry(
        without_f2, assigned_ids=["F2", "F4", "not-an-id"]
    )
    assert new_id == "F5"
    assert set(fatigue_inputs.detail_ids(reserved)) == {"F1", "F3", "F5"}
