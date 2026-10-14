"""Action tab navigation retains separate authoritative case families."""
from types import SimpleNamespace

import pandas as pd
import pytest

from app import action_workspace as actions
from app import fatigue_inputs, load_cases


class TabHost:
    open = True

    def __init__(self, state):
        self.state = state
        self.labels = None

    def tabs(self, labels, **kwargs):
        self.labels = tuple(labels)
        assert kwargs["key"] == actions.FAMILY_KEY
        return [SimpleNamespace(open=self.state[actions.FAMILY_KEY] == label)
                for label in labels]


@pytest.mark.parametrize("selected", ["Plastic", "Elastic", "Fatigue"])
def test_actions_tab_switch_preserves_all_canonical_tables(selected):
    state = load_cases.default_tables()
    state[fatigue_inputs.SPECTRUM_TABLE_KEY] = fatigue_inputs.normalise_spectrum_table([
        {"name": "Bin 1", "spectrum": "Traffic", "cycles": 12345},
    ])
    state[actions.FAMILY_KEY] = selected
    tables = {key: frame.copy(deep=True) for key, frame in state.items()
              if isinstance(frame, pd.DataFrame)}
    host = TabHost(state)
    stages = actions.family_stages(host, state=state)
    assert host.labels == ("Plastic", "Elastic", "Fatigue")
    assert [stage.open for stage in stages] == [selected == label for label in host.labels]
    assert state[actions.FAMILY_KEY] == selected
    assert actions.FAMILIES == ("Plastic", "Elastic")
    assert tuple(actions.TABLES.values()) == load_cases.CASE_TABLE_KEYS
    for key, frame in tables.items():
        pd.testing.assert_frame_equal(state[key], frame, check_exact=True)


def test_actions_conventions_keep_signs_and_fatigue_definition():
    class Guide:
        def __init__(self):
            self.paragraphs = []

        def expander(self, *args, **kwargs):
            return self

        def markdown(self, text):
            self.paragraphs.append(text)

    guide = Guide()
    actions.conventions(guide)
    assert all(len(paragraph.split()) <= 50 for paragraph in guide.paragraphs)
    text = " ".join(guide.paragraphs)
    for required in ("+x points right", "+y points up", "positive N is tension",
                     "positive Mx compresses the top", "positive My compresses the right",
                     "Vx pairs with My", "Vy pairs with Mx", "additional increments",
                     "basic and combined states elastically", "fatigue-bin tables"):
        assert required in text
