"""Selected UI contour preserves accepted values and avoids duplicate maps."""
import ast
import pickle
import re
from pathlib import Path
import pytest
from test_section_fields import native_case
from app import section_fields

SOURCE = Path(__file__).resolve().parents[1] / "app" / "sector_app.py"

class Surface:
    def __init__(self, quantity, duration):
        self.values = {"Contour quantity": quantity, "Map action duration": duration}
        self.charts, self.tables, self.controls, self.notes = [], [], [], []
        self.chart_options = []
    def segmented_control(self, label, options, **kwargs):
        self.controls.append((label, options, kwargs))
        assert kwargs["required"] is True
        assert kwargs["persist_state"] == "session"
        return self.values[label]
    def plotly_chart(self, figure, **kwargs):
        self.charts.append(figure)
        self.chart_options.append(kwargs)
    def dataframe(self, rows, **kwargs): self.tables.append(rows)
    def caption(self, text): self.notes.append(text)
    def markdown(self, text): self.notes.append(text)
    def info(self, text): self.notes.append(text)

def panel(surface):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_section_field_panel")
    ns = dict(st=surface, section_fields=section_fields, _PERMILLE="\u2030", _MM=1000., re=re)
    safe = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_safe_filename_part")
    exec(compile(ast.Module(body=[safe], type_ignores=[]), str(SOURCE), "exec"), ns)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns[fn.name]

@pytest.mark.parametrize("family,duration", [("Plastic", "TOTAL"), ("Elastic", "TOTAL"), ("Elastic", "LONG")])
@pytest.mark.parametrize("quantity", ["stress", "strain"])
def test_selected_contour_exact_native_values_and_no_result_mutation(family, duration, quantity):
    inp, elastic, plastic, _ = native_case(phi=2., tendon=True)
    result = {"points": [plastic]} if family == "Plastic" else elastic
    kwargs = {"point_index": 0} if family == "Plastic" else {}
    expected_field, expected_maps = section_fields.field_pair(inp, result, family=family, duration=duration, **kwargs)
    before = pickle.dumps((inp, result))
    surface = Surface(quantity, duration)
    panel(surface)(inp, result, family=family, **kwargs)
    assert len(surface.charts) == len(surface.tables) == 1
    assert surface.charts[0].to_json() == dict(expected_maps)[quantity].to_json()
    unit = "\u2030" if quantity == "strain" else "MPa"
    assert surface.tables[0] == [{"Extremum": label, f"Value ({unit})": value, "x (mm)": x*1000, "y (mm)": y*1000}
                                 for label,value,x,y in section_fields.extrema(expected_field, quantity)]
    export = surface.chart_options[0]["config"]["toImageButtonOptions"]
    assert export["format"] == "png"
    assert f"_{family}_{quantity}_" in export["filename"]
    assert "Ultimate_capacity" in export["filename"] if family == "Plastic" else duration in export["filename"]
    assert export["width"] is None and export["height"] is None
    assert expected_field.state + ". " + expected_field.caption in surface.notes
    assert len(surface.controls) == (2 if family == "Elastic" else 1)
    assert pickle.dumps((inp, result)) == before

@pytest.mark.parametrize("family", ["Plastic", "Elastic"])
def test_stale_evidence_publishes_no_contour_or_extrema(family):
    inp, elastic, plastic, _ = native_case()
    result = {"points": [dict(plastic, field_context="obsolete")]} if family == "Plastic" else dict(elastic, field_context="obsolete")
    surface = Surface("stress", "TOTAL")
    panel(surface)(inp, result, family=family, point_index=0 if family=="Plastic" else None)
    assert not surface.charts and not surface.tables
    assert any("unavailable" in n for n in surface.notes)


def test_native_widgets_keep_quantity_and_duration_across_hidden_view():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string(_native_widget_source(), default_timeout=30).run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    controls = {w.key: w for w in app.get("button_group")}
    controls["elastic_field_quantity"].set_value("strain")
    controls["elastic_field_duration"].set_value("LONG")
    app.run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    app.checkbox(key="show_maps").uncheck().run()
    assert not app.get("plotly_chart")
    app.checkbox(key="show_maps").check().run()
    assert not app.exception
    controls = {w.key: w for w in app.get("button_group")}
    assert controls["elastic_field_quantity"].value == "strain"
    assert controls["elastic_field_duration"].value == "LONG"
    assert len(app.get("plotly_chart")) == 1
    assert any("Elastic LONG" in c.value for c in app.caption)


def _native_widget_source():
    return 'import ast\nimport re\nfrom pathlib import Path\nfrom types import SimpleNamespace\nimport streamlit as st\nimport plotly.graph_objects as go\nsource=Path(SOURCE_PATH)\ntree=ast.parse(source.read_text(encoding="utf-8"))\nfn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_section_field_panel")\nclass Missing(ValueError): pass\ndef pair(inp,result,**kw):\n    field=SimpleNamespace(state=kw["family"]+" "+kw["duration"],caption="Test retained state",density=False)\n    return field, [(q,go.Figure(go.Scatter(x=[0,1],y=[1,2],name=q))) for q in ("stress","strain")]\nsafe=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_safe_filename_part")\nns=dict(re=re,st=st,section_fields=SimpleNamespace(FieldUnavailable=Missing,field_pair=pair,extrema=lambda f,q:[("Concrete",2.,0.,0.)]),_PERMILLE="\\u2030",_MM=1000.)\nexec(compile(ast.Module(body=[safe,fn],type_ignores=[]),str(source),"exec"),ns)\nvisible=st.checkbox("Show maps",value=True,key="show_maps")\nif visible: ns[fn.name]({}, {}, family="Elastic")\n'.replace("SOURCE_PATH", repr(str(SOURCE)))
