"""Report pagination regressions with native ReportLab layout and real helpers."""

import ast
import copy
import io
from pathlib import Path

import pypdf
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Flowable

from app import sector_report as report

path = Path(report.__file__)


class Block(Flowable):
    def __init__(self, height, label):
        super().__init__()
        self.height = height
        self.width = 400
        self.label = label

    def draw(self):
        self.canv.drawString(0, 5, self.label)


def builder(profile="Audit"):
    return report.ReportBuilder(
        io.BytesIO(), {}, {}, {}, figures=False, profile=profile
    )


def pdf(b):
    stream = io.BytesIO()
    doc = report._ReportDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    doc.multiBuild(b.flow)
    data = stream.getvalue()
    pages = [p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages]
    assert all(page.strip() for page in pages)
    return pages


def page(pages, text):
    found = [i for i, p in enumerate(pages) if text in p]
    assert len(found) == 1, (text, found)
    return found[0]


@pytest.mark.parametrize("profile", ["Brief", "Standard", "Audit"])
@pytest.mark.parametrize("rows", [2, 90])
@pytest.mark.parametrize("keep", [True, False])
def test_explicit_small_heading_and_table_split(profile, rows, keep):
    b = builder(profile)
    b.flow.append(Block(640, "PREVIOUS CONTENT"))
    b._small("<b>EXACT DATA HEADING</b>", keep_with_next=True)
    b._table(
        [["Identity", "Value"]] + [[f"ITEM-{i:03}", str(i)] for i in range(rows)],
        [100 * mm, 60 * mm],
        keep=keep,
        caption="Complete data population",
    )
    pages = pdf(b)
    assert page(pages, "EXACT DATA HEADING") == page(pages, "ITEM-000")
    text = "\n".join(pages)
    for i in range(rows):
        assert text.count(f"ITEM-{i:03}") == 1
    for p in pages:
        if "ITEM-" in p:
            assert "Identity" in p and "Complete data population" in p
    if rows == 90:
        assert page(pages, "ITEM-089") > page(pages, "ITEM-000")


@pytest.mark.parametrize("rows", [2, 70])
@pytest.mark.parametrize("keep", [True, False])
def test_multi_panel_table_leads_keep_first_row_and_all_values(rows, keep):
    b = builder()
    b.flow.append(Block(590, "PREVIOUS CONTENT"))
    b._small("<b>MULTI PANEL DATA</b>", keep_with_next=True)
    headers = ["Identity"] + [f"Column {j} engineering result" for j in range(1, 9)]
    data = [headers] + [
        [f"ROW-{i:03}"] + [f"C{j}R{i:03}" for j in range(1, 9)] for i in range(rows)
    ]
    b._table(data, [40 * mm] * 9, keep=keep, caption="Full multi-panel population")
    pages = pdf(b)
    text = "\n".join(pages)
    assert "Column panel 2 of " in text
    for j in range(1, 9):
        for i in range(rows):
            assert text.count(f"C{j}R{i:03}") == 1
    for p in pages:
        if "Column panel " in p:
            assert "ROW-" in p, p
            assert "Full multi-panel population" in p
    assert page(pages, "MULTI PANEL DATA") == next(
        i for i, p in enumerate(pages) if "ROW-000" in p
    )


@pytest.mark.parametrize("n", [2, 95])
def test_real_sweep_labels_keep_first_substantive_row(n):
    b = builder()
    b.flow.append(Block(600, "PREVIOUS CONTENT"))
    points = [
        {
            "V": i,
            "Mx": 8000 + i,
            "My": 9000 + i,
            "na_x": 0.01,
            "na_y": 0.02,
            "eps_c": 0.3,
            "eps_s": 0.4,
            "kappa": 0.005,
            "comp_force": 500,
            "lever": 0.3,
            "dx": 0.1,
            "dy": 0.2,
        }
        for i in range(n)
    ]
    b._plastic_sweep_population({"points": points})
    pages = pdf(b)
    for label, token in [
        ("Capacity and neutral axis", "8000.000"),
        ("Strain and equilibrium detail", "500.000"),
    ]:
        p = pages[page(pages, label)]
        assert token in p
        assert "NA angle" in p
    text = "\n".join(pages)
    for i in range(n):
        assert text.count(f"{8000 + i}.000") == 1
    assert text.count("500.000") == n


@pytest.mark.parametrize("figures", [True, False])
@pytest.mark.parametrize(
    "check_util,applied", [(True, (20, 30)), (True, None), (False, (20, 30))]
)
def test_real_nm_branch_groups_complete_conditional_explanation(
    monkeypatch, figures, check_util, applied
):
    # Execute the unchanged production N-M branch; replace only image export.
    tree = ast.parse(path.read_text())
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "ReportBuilder"
    )
    method = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_plastic"
    )
    branch = next(
        n
        for n in method.body
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "nm"
    )
    namespace = dict(report.__dict__)
    b = builder("Standard")
    b.figures = figures
    b.flow.append(Block(450, "PREVIOUS CONTENT"))
    captured = []

    def fig(data, *args, **kwargs):
        captured.append(data)
        b.flow.append(Block(275, "FIGURE-" + data["axis"]))

    monkeypatch.setattr(b, "_fig", fig)
    monkeypatch.setattr(
        report.viz,
        "interaction_nm_figure",
        lambda n, m, **kwargs: dict(n=n, m=m, **kwargs),
    )
    nm = {axis: {"N": [1, 2], "M": [3, 4], "applied": applied} for axis in ["x", "y"]}
    before = copy.deepcopy(nm)
    namespace.update(self=b, nm=nm, pl={"check_util": check_util})
    exec(  # noqa: S102 - trusted repository branch under test
        compile(ast.Module(body=[branch], type_ignores=[]), str(path), "exec"),
        namespace,
    )
    assert nm == before
    pages = pdf(b)
    for axis in ["x", "y"]:
        at = page(pages, f"The capacity boundary about the {axis}-axis")
        assert "Concrete carries compression only." in pages[at]
        if figures:
            assert page(pages, "FIGURE-" + axis) == at
        assert ("The marked point is the applied plastic action." in pages[at]) == (
            check_util and applied is not None
        )
    if figures:
        assert [v["applied"] for v in captured] == [applied if check_util else None] * 2


def test_all_authored_short_labels_have_explicit_continuation():
    tree = ast.parse(path.read_text())
    labels = {
        "Scope and calculation state",
        "Grouped fatigue spectra",
        "Plastic / capacity cases",
        "Elastic cases",
        "Capacity and neutral axis",
        "Strain and equilibrium detail",
    }
    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_small"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            value = node.args[0].value
            if value in {f"<b>{label}</b>" for label in labels}:
                assert any(
                    k.arg == "keep_with_next"
                    and isinstance(k.value, ast.Constant)
                    and k.value.value is True
                    for k in node.keywords
                )
                found.add(value[3:-4])
    assert found == labels


def test_retained_matrix_title_and_qualifications_stay_with_matrix():
    b = builder()
    b.flow.append(Block(400, "PREVIOUS CONTENT"))
    state = {
        "raw_stress_plane": {
            "sigma0_kpa": 1,
            "gradient_x_kpa_per_m": 2,
            "gradient_y_kpa_per_m": 3,
        },
        "equilibrium": {
            "matrix": [[11, 12, 13], [21, 22, 23], [31, 32, 33]],
            "target": {"n": 1, "mx": 2, "my": 3},
            "internal": {"n": 1, "mx": 2, "my": 3},
            "residual": {"n": 0, "mx": 0, "my": 0},
            "normalised_residual": 0,
            "relative_tolerance": 1e-9,
        },
        "iterations": 6,
    }
    before = copy.deepcopy(state)
    b._elastic_state_tables("RETAINED NATIVE MATRIX", state)
    assert state == before
    pages = pdf(b)
    at = page(pages, "Final transformed equilibrium matrix J:")
    for text in [
        "11.000000000",
        "33.000000000",
        "The N row has column units",
        "The reference-stress plane has coefficient units",
    ]:
        assert text in pages[at]
    assert pages[at].index("Final transformed equilibrium matrix J:") < pages[at].index(
        "11.000000000"
    )


def test_oversized_explanation_group_still_splits_without_loss():
    b = builder()
    b.flow.append(Block(450, "PREVIOUS CONTENT"))
    start = len(b.flow)
    b.flow.append(Block(275, "ILLUSTRATIVE FIGURE"))
    for i in range(100):
        b._small(f"EXPLANATION-{i:03}: retained explanatory content.")
    b._keep_from(start)
    pages = pdf(b)
    assert len(pages) > 2
    text = "\n".join(pages)
    for i in range(100):
        assert text.count(f"EXPLANATION-{i:03}:") == 1


@pytest.mark.parametrize("columns", [2, 10])
def test_tall_table_uses_remaining_page_below_short_label(columns):
    b = builder("Standard")
    b.flow.append(Block(300, "PREVIOUS CONTENT"))
    b._small("<b>TALL TABLE LABEL</b>", keep_with_next=True)
    data = [["Row identity"] + [f"Column {j} result" for j in range(1, columns)]]
    data += [
        [f"ROW-{i:03}"] + [f"C{j}R{i:03}" for j in range(1, columns)] for i in range(80)
    ]
    b._table(data, [40 * mm] * columns, keep=False, caption="Tall table record")
    pages = pdf(b)
    assert "TALL TABLE LABEL" in pages[0]
    assert "ROW-000" in pages[0]
    for j in range(1, columns):
        for i in range(80):
            assert "\n".join(pages).count(f"C{j}R{i:03}") == 1


@pytest.mark.parametrize("following", [False, True])
def test_labelled_table_gap_cannot_create_empty_final_page(following):
    b = builder("Standard")
    b.flow.append(Block(620, "PREVIOUS CONTENT"))
    b._small("<b>FINAL TABLE LABEL</b>", keep_with_next=True)
    b._table(
        [["Identity", "Result"]] + [[f"ROW-{i:03}", str(i)] for i in range(80)],
        [100 * mm, 60 * mm],
        keep=False,
        caption="Final population",
    )
    table = next(v for v in b.flow if isinstance(v, report._PaginatedReportTable))
    assert table.getSpaceAfter() == 4
    # ReportLab must retain the gap only on the last vertical fragment.
    table.wrap(170 * mm, 700)
    fragments = table.split(170 * mm, 300)
    assert len(fragments) == 2
    assert fragments[0].getSpaceAfter() == 0
    assert fragments[-1].getSpaceAfter() == 4
    if following:
        b._small("FOLLOWING CONTENT")
    pages = pdf(b)
    assert len(pages) == 3
    assert "ROW-079" in pages[-1]
    if following:
        assert "FOLLOWING CONTENT" in pages[-1]
