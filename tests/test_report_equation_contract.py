from __future__ import annotations

import ast
import collections
from dataclasses import FrozenInstanceError
import io
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import report_equation_contract as contracts  # noqa: E402
import sector_report  # noqa: E402


EXPECTED_CONTRACT_KEYS = {
    ("basis.detailing.transverse-ratios", None),
    ("basis.fatigue.concrete-miner", None),
    ("basis.fatigue.reinforcement-miner", None),
    ("basis.fatigue.stress-range", None),
    ("basis.plastic.equilibrium", None),
    ("basis.plastic.governing-curvature", None),
    ("combined.chord.demand", None),
    ("combined.chord.utilisation", None),
    ("combined.crushing.interaction", None),
    ("combined.dk-na.sum", None),
    ("combined.stirrup.utilisation", None),
    ("crack.2005.mean-strain", None),
    ("crack.2005.spacing", "geometric"),
    ("crack.2005.spacing", "reinforcement"),
    ("crack.2005.width", None),
    ("crack.2023.mean-strain", None),
    ("crack.2023.spacing", None),
    ("crack.2023.width", None),
    ("cracking.threshold", None),
    ("detailing.clear-spacing.requirement", None),
    ("detailing.links.minimum-ratio", None),
    ("detailing.minimum.area-2005", None),
    ("detailing.minimum.bending-2023", None),
    ("detailing.minimum.tension-2023", None),
    ("materials.concrete.curve-2", None),
    ("materials.concrete.fcd", "2005"),
    ("materials.concrete.fcd", "2023"),
    ("materials.steel.fyd-N", None),
    ("plastic.worked.axial-equilibrium", None),
    ("shear.2005.stress-basic", None),
    ("shear.2005.stress-minimum", None),
    ("shear.2005.utilisation", None),
    ("shear.2005.vrdc", None),
    ("shear.2023.axial-factor", None),
    ("shear.2023.effective-span", None),
    ("shear.2023.tau-basic", None),
    ("shear.2023.tau-minimum", None),
    ("shear.2023.utilisation", None),
    ("shear.2023.vrdc", None),
    ("shear.chord.demand", "2005"),
    ("shear.chord.demand", "2023"),
    ("shear.chord.utilisation", None),
    ("shear.links.sigma-field", None),
    ("shear.links.tau-yield", None),
    ("shear.links.utilisation", None),
    ("shear.links.vrd", None),
    ("shear.links.vrdmax", "2005"),
    ("shear.links.vrdmax", "2023"),
    ("shear.links.vrds", "2005"),
    ("shear.links.vrds", "2023"),
    ("torsion.cracking.fctd", None),
    ("torsion.cracking.resistance", None),
    ("torsion.longitudinal-steel", None),
    ("torsion.minimum-reinforcement.screen", None),
    ("torsion.off-axis-chord.demand", None),
    ("torsion.off-axis-chord.utilisation", None),
    ("torsion.resistance.crushing", None),
    ("torsion.resistance.governing", None),
    ("torsion.resistance.steel", None),
    ("torsion.shear.crushing-interaction", None),
    ("torsion.subtube.governing-utilisation", None),
    ("torsion.utilisation", None),
}

THEORY_ONLY_EQUATIONS = {
    ("basis.detailing.transverse-ratios", None),
    ("basis.fatigue.concrete-miner", None),
    ("basis.fatigue.reinforcement-miner", None),
    ("basis.fatigue.stress-range", None),
    ("basis.plastic.equilibrium", None),
    ("basis.plastic.governing-curvature", None),
    ("materials.concrete.curve-2", None),
}

# This is an executable PR-03 work list, not a permanent allowance. Each family
# slice removes its entries by publishing a numerical substitution and result.
EXISTING_LIVE_EQUATION_GAPS = {
    ("combined.dk-na.sum", None),
    ("crack.2005.mean-strain", None),
    ("crack.2005.spacing", "geometric"),
    ("crack.2005.spacing", "reinforcement"),
    ("crack.2023.mean-strain", None),
    ("crack.2023.spacing", None),
    ("detailing.clear-spacing.requirement", None),
    ("detailing.links.minimum-ratio", None),
    ("detailing.minimum.area-2005", None),
    ("detailing.minimum.bending-2023", None),
    ("detailing.minimum.tension-2023", None),
    ("shear.links.vrd", None),
    ("torsion.resistance.governing", None),
    ("torsion.subtube.governing-utilisation", None),
}


def _formula_calls():
    path = ROOT / "app" / "sector_report.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    return source, [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_formula"
    ]


def _authored_pairs(call):
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    key_node = keywords["equation_key"]
    if isinstance(key_node, ast.Constant):
        key = key_node.value
    else:
        assert ast.unparse(key_node) == (
            "f'materials.steel.fyd-{material_index + 1}'"
        )
        key = "materials.steel.fyd-N"

    variant_node = keywords.get("equation_variant")
    if variant_node is None:
        variants = (None,)
    elif isinstance(variant_node, ast.Constant):
        variants = (variant_node.value,)
    else:
        assert isinstance(variant_node, ast.IfExp)
        variants = (variant_node.body.value, variant_node.orelse.value)
    return {(key, variant) for variant in variants}


def _builder():
    return sector_report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, qa_appendix=False
    )


def test_catalogue_exactly_covers_every_live_call_and_variant():
    _source, calls = _formula_calls()
    assert len(calls) == 61
    assert all(
        not any(keyword.arg == "equation_spec" for keyword in call.keywords)
        for call in calls
    ), "production call sites must not bypass the frozen catalogue"

    authored_pairs = set()
    for call in calls:
        authored_pairs.update(_authored_pairs(call))

    catalogue_pairs = {key for key, _contract in contracts.equation_contract_items()}
    assert len(catalogue_pairs) == 62
    assert catalogue_pairs == EXPECTED_CONTRACT_KEYS
    assert authored_pairs == EXPECTED_CONTRACT_KEYS


def test_every_contract_is_complete_immutable_and_role_pinned():
    items = contracts.equation_contract_items()
    publication_role_counts = collections.Counter(
        contract.publication_role for _key, contract in items
    )
    role_counts = collections.Counter(
        contract.substitution_role for _key, contract in items
    )
    result_counts = collections.Counter(
        contract.expects_result for _key, contract in items
    )
    assert role_counts == {
        "numerical": 42,
        "none": 20,
    }
    assert publication_role_counts == {"calculation": 55, "theory": 7}
    # One extra contract is the second runtime branch of shear.chord.demand.
    assert result_counts == {True: 46, False: 16}

    for (key, _variant), contract in items:
        assert contract.symbols, key
        names = [symbol.markup for symbol in contract.symbols]
        assert len(names) == len(set(names)), key
        assert all(
            symbol.markup.strip()
            and symbol.meaning.strip()
            and symbol.unit.strip()
            for symbol in contract.symbols
        ), key
        if contract.expects_result:
            assert contract.result_symbol in names, key
            assert contract.result_unit and contract.result_unit.strip(), key
        else:
            assert contract.result_unit is None, key
        if contract.publication_role == "theory":
            assert not contract.expects_result, key
            assert not contract.expects_substitution, key
            assert not contract.applicability_note_required, key

    with pytest.raises(FrozenInstanceError):
        items[0][1].result_unit = "changed"


def test_theory_and_existing_live_equation_gap_inventory_are_exact():
    items = contracts.equation_contract_items()
    theory = {
        key for key, contract in items if contract.publication_role == "theory"
    }
    incomplete_calculations = {
        key
        for key, contract in items
        if contract.publication_role == "calculation"
        and (
            contract.substitution_role != "numerical"
            or not contract.expects_result
        )
    }

    assert theory == THEORY_ONLY_EQUATIONS
    assert incomplete_calculations == EXISTING_LIVE_EQUATION_GAPS
    assert not theory & incomplete_calculations


def test_dynamic_material_identity_and_variant_selection_are_exact():
    template = contracts.equation_contract("materials.steel.fyd-1")
    assert contracts.equation_contract("materials.steel.fyd-999") is template
    assert template.result_symbol == "f<sub>yd</sub>"
    assert template.result_unit == "MPa"

    with pytest.raises(ValueError, match="requires one of variants"):
        contracts.equation_contract("materials.concrete.fcd")
    with pytest.raises(ValueError, match="got 'future'"):
        contracts.equation_contract("materials.concrete.fcd", "future")
    with pytest.raises(ValueError, match="No report equation contract"):
        contracts.equation_contract("unknown.valid-key")
    with pytest.raises(ValueError, match="No report equation contract"):
        contracts.equation_contract("materials.steel.fyd-0")


def test_review_regressions_have_distinct_roles_and_complete_result_identity():
    combined = contracts.equation_contract("combined.dk-na.sum")
    geometric = contracts.equation_contract(
        "crack.2005.spacing", "geometric"
    )
    assert combined.substitution_role == "none"
    assert geometric.substitution_role == "none"
    assert combined.applicability_note_required
    assert geometric.applicability_note_required

    crack = contracts.equation_contract("crack.2023.width")
    definitions = {symbol.markup: symbol.meaning for symbol in crack.symbols}
    assert crack.result_symbol == "w<sub>k</sub>"
    assert "w<sub>k,cal</sub>" in definitions
    assert "w<sub>k</sub>" in definitions
    assert "equal to w<sub>k,cal</sub>" in definitions["w<sub>k</sub>"]


@pytest.mark.parametrize(
    ("key", "variant", "substitution", "note", "result"),
    [
        ("materials.concrete.fcd", "2023", None, None, "fcd = 1 MPa"),
        ("materials.concrete.fcd", "2023", "1 x 2", None, None),
        ("materials.concrete.fcd", "2023", None, "method prose", "fcd = 1 MPa"),
        ("combined.dk-na.sum", None, "0.4 + 0.3", None, "sum = 0.7"),
        ("combined.dk-na.sum", None, None, None, "sum = 0.7"),
        ("basis.plastic.equilibrium", None, "1 + 2", None, None),
        ("basis.plastic.equilibrium", None, None, "extra prose", None),
        ("basis.plastic.equilibrium", None, None, None, "N = 0"),
    ],
)
def test_incompatible_missing_and_sibling_evidence_fail_atomically(
    key, variant, substitution, note, result
):
    builder = _builder()
    builder._h1("Contract probe")
    flow_before = len(builder.flow)
    equations_before = dict(builder._equations)
    number_before = builder._equation_number
    with pytest.raises(ValueError, match="requires"):
        builder._formula(
            "x = y",
            equation_key=key,
            equation_variant=variant,
            subst=substitution,
            note=note,
            result=result,
        )
    assert len(builder.flow) == flow_before
    assert builder._equations == equations_before
    assert builder._equation_number == number_before


def test_contract_metadata_reaches_the_equation_flowable_unchanged():
    builder = _builder()
    builder._h1("Materials")
    builder._formula(
        "f<sub>cd</sub> = eta<sub>cc</sub> k<sub>tc</sub> "
        "f<sub>ck</sub> / gamma<sub>c</sub>",
        equation_key="materials.concrete.fcd",
        equation_variant="2023",
        subst="0.9 x 0.85 x 40 / 1.5",
        result="f<sub>cd</sub> = 20.4 MPa",
    )
    equation = builder.flow[-1]
    contract = contracts.equation_contract("materials.concrete.fcd", "2023")
    assert equation._sector_equation_variant == "2023"
    assert equation._sector_equation_symbols == contract.symbols
    assert equation._sector_equation_result_symbol == "f<sub>cd</sub>"
    assert equation._sector_equation_result_unit == "MPa"
    assert equation._sector_equation_substitution_role == "numerical"
    assert equation._sector_equation_publication_role == "calculation"
    assert not equation._sector_equation_applicability_note_required

    builder._h2("Applicability")
    builder._formula(
        "max(rM + rT, rV + rT)",
        equation_key="combined.dk-na.sum",
        note="M and V are checked separately.",
        result="sum(S<sub>Ed</sub>/S<sub>Rd</sub>) = 0.70",
    )
    note_equation = builder.flow[-1]
    assert note_equation._sector_equation_substitution_role == "none"
    assert note_equation._sector_equation_applicability_note_required
    assert "M and V are checked separately." in note_equation.getPlainText()


def test_numerical_substitution_and_applicability_note_are_independent():
    builder = _builder()
    builder._h1("Independent publication rows")
    contract = contracts.EquationContract(
        symbols=(
            contracts.EquationSymbol("x", "input", "kN"),
            contracts.EquationSymbol("y", "result", "kN"),
        ),
        result_symbol="y",
        result_unit="kN",
        substitution_role="numerical",
        publication_role="calculation",
        applicability_note_required=True,
    )
    builder._formula(
        "y = 2x",
        equation_key="test.numerical-with-note",
        equation_spec=contract,
        subst="= 2 x 3 kN",
        note="This branch applies because the declared condition is true.",
        result="y = 6 kN",
    )
    equation = builder.flow[-1]
    assert equation._sector_equation_substitution_role == "numerical"
    assert equation._sector_equation_applicability_note_required
    roles = equation._sector_equation_roles
    assert "symbolic-expression" in roles
    assert "numerical-substitution" in roles
    assert "applicability-note" in roles
    assert "result" in roles
    assert roles.index("numerical-substitution") < roles.index("applicability-note")
    assert roles.index("applicability-note") < roles.index("result")

    with pytest.raises(ValueError, match="requires an applicability note"):
        builder._formula(
            "y = 2x",
            equation_key="test.numerical-with-note",
            equation_spec=contract,
            subst="= 2 x 3 kN",
            result="y = 6 kN",
        )


def test_explicit_test_contract_cannot_mask_a_variant_or_wrong_type():
    builder = _builder()
    builder._h1("Test-only override")
    relation = contracts.EquationContract(
        symbols=(contracts.EquationSymbol("x", "test symbol"),)
    )
    with pytest.raises(ValueError, match="cannot also select a variant"):
        builder._formula(
            "x = 1",
            equation_key="test.synthetic",
            equation_variant="one",
            equation_spec=relation,
        )
    with pytest.raises(TypeError, match="EquationContract"):
        builder._formula(
            "x = 1", equation_key="test.synthetic", equation_spec=object()
        )
