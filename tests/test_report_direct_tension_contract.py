"""Native uniform tension has an explicit infinite spacing cap in the report."""
import copy
import io
import pickle
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import sector_report as report
from sector.serviceability import analyse_cracking
from sector.section import Section
from sector_app import _crack_dict


def _native(direct=True):
    bars = [(-.1, -.25, 400.), (.1, -.25, 400.), (-.1, .25, 400.), (.1, .25, 400.)]
    section = Section.from_polygon([(-.15,-.3),(.15,-.3),(.15,.3),(-.15,.3)], bars)
    actions = (-800., 0., 0.) if direct else (0., 150., 0.)
    result = analyse_cracking(section, *actions, 6., fctm=3., bar_diameter=20., edition="2023")
    return _crack_dict(result.crack, ["R1", "R2", "R3", "R4"])


@pytest.mark.parametrize("direct", [False, True])
def test_native_2023_report_operands_are_complete_and_immutable(direct):
    cw = _native(direct)
    original = pickle.dumps(cw)
    assert report.ReportBuilder._crack_worked_missing_operands(cw) == ()
    builder = report.ReportBuilder(io.BytesIO(), {}, {}, {}, profile="Audit", figures=False)
    formulas = []
    builder._formula = lambda *args, **kwargs: formulas.append((args, kwargs))
    builder._crack_worked_2023(cw, cw["governing_candidate"])
    spacing = next(k for _, k in formulas if k["equation_key"] == "crack.2023.spacing")
    assert "no finite tension-zone cap" not in spacing["subst"]
    assert ("no finite tension-zone cap" in spacing["note"]) is direct
    assert pickle.dumps(cw) == original
    assert formulas[-1][1]["result"] == "w<sub>k</sub> = " + report._fmt(cw["wk"], 3) + " mm"


@pytest.mark.parametrize("fault", ["record", "method", "selected", "missing-depth", "missing-cap", "finite-depth", "finite-cap", "missing-diameter"])
def test_direct_branch_rejects_inconsistent_or_missing_retained_operands(fault):
    cw = _native()
    spacing = cw["governing_candidate"]["spacing_operands"]
    if fault == "record":
        cw["effective_area_operands"]["record_kind"] = "CrackEffectiveArea2023Bending"
    elif fault == "method":
        spacing["flexural_factor_method"] = "formula-9.20"
    elif fault == "selected":
        spacing["selected_candidate"] = "tension-zone-cap"
    elif fault == "missing-depth":
        del spacing["cap_tension_depth"]
    elif fault == "missing-cap":
        del spacing["cap_spacing"]
    elif fault == "finite-depth":
        spacing["cap_tension_depth"] = .2
    elif fault == "finite-cap":
        spacing["cap_spacing"] = 250.
    else:
        del spacing["diameter"]
    assert report.ReportBuilder._crack_worked_missing_operands(cw)


@pytest.mark.parametrize("field", ["cap_tension_depth", "cap_spacing"])
@pytest.mark.parametrize("fault", ["missing", "null"])
def test_bending_requires_both_retained_cap_operands(field, fault):
    cw = _native(False)
    spacing = cw["governing_candidate"]["spacing_operands"]
    if fault == "missing":
        del spacing[field]
    else:
        spacing[field] = None
    assert "spacing." + field in report.ReportBuilder._crack_worked_missing_operands(cw)


@pytest.mark.parametrize("value,expected", [
    ("Ribbed / high bond (k1 = 0.8)", "Ribbed / high bond (k<sub>1</sub> = 0.8)"),
    ("Plain round (k1 = 1.6)", "Plain round (k<sub>1</sub> = 1.6)"),
    ("User <sub>literal</sub> & k1 = 9", "User &#60;sub&#62;literal&#60;/sub&#62; &amp; k1 = 9"),
    ("Ribbed / high bond (k1 = 0.8) extra", "Ribbed / high bond (k1 = 0.8) extra"),
])
@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
def test_only_closed_bond_choices_receive_authored_notation(profile, value, expected):
    from tools.report_render_fixture import _inputs
    from sector.design_standards import DesignBasisKey
    inp = _inputs()
    inp["tendons"] = [(-.1, -.25, 150.)]
    inp.update(sls_bond=value, sls_edition="2023", sls_code=DesignBasisKey.PUBLISHED_2023.value, sls_tendon_xi=.5)
    original = pickle.dumps(inp)
    builder = report.ReportBuilder(io.BytesIO(), {}, inp, {}, profile=profile, figures=False)
    tables = []
    builder._table = lambda rows, *a, **kw: tables.append(copy.deepcopy(rows))
    builder._brief_settings_summary()
    assert expected in str(tables)
    assert "Bonded-tendon bond-strength ratio &#958;" in str(tables)
    assert pickle.dumps(inp) == original
