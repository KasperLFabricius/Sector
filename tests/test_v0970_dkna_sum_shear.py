"""TB-04: the DK NA 6.3.2(6) sum uses the section resistance to V acting alone.

With VRd,c = 100 kN and valid links with VRd,s = 300 kN, the resistance to V acting
alone is 300 kN for every VEd. The term VEd/VRd is then monotonic in VEd: 95 kN
gives 95/300 and 105 kN gives 105/300. Before 0.97.0 the term was 95/100 below
VRd,c and 105/300 above it.
"""

from __future__ import annotations

import pytest

from sector import capacity


def _patch(monkeypatch, v_ed):
    def fake_context(face_input, n_prestress, n_ed_comp):
        payload = {"res": {"valid": True}, "v_ed": v_ed}
        context = {
            "build": lambda lo, hi: {"valid": True, "vrd": 300.0, "cot": 2.5},
            "cot_min": 1.0,
            "cot_max": 2.5,
        }
        return payload, context

    def fake_selection(shear_payload, *, links_selected):
        route = "concrete" if shear_payload["v_ed"] <= 100.0 else "links"
        resistance = 100.0 if route == "concrete" else 300.0
        return capacity.NominalShearResistanceSelection(
            valid=True, route=route, resistance=resistance,
            utilisation=shear_payload["v_ed"] / resistance, status="PASS",
            ok=True, concrete_applicable=route == "concrete",
            links_selected=links_selected, links_required=route == "links",
            reason=None,
        )

    monkeypatch.setattr(capacity, "build_shear_context", fake_context)
    monkeypatch.setattr(capacity, "select_nominal_shear_resistance", fake_selection)
    monkeypatch.setattr(capacity, "prestress_axial", lambda _inp: 0.0)


@pytest.mark.parametrize("v_ed", (95.0, 105.0))
def test_shear_alone_resistance_uses_links_when_they_resist_more(monkeypatch, v_ed):
    _patch(monkeypatch, v_ed)
    record = capacity._dkna_shear_action_alone(
        {"shear_V": v_ed, "shear_axis": "x", "shear_face_y": "negative"}
    )
    assert record["valid"] is True
    assert record["resistance"] == pytest.approx(300.0)
    assert record["demand"] / record["resistance"] == pytest.approx(v_ed / 300.0)
