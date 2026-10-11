"""Keep active AppTest controls when a closed Quick Section fragment remains."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tests")]

from app_case_inputs import discard_retired_qs_fragment


@pytest.mark.parametrize("has_input_stage", [False, True])
@pytest.mark.parametrize("builder_open", [False, True])
def test_cleanup_preserves_live_controls_and_state(has_input_stage, builder_open):
    live = NS(key="_input_tab" if has_input_stage else "calculate")
    retired = NS(children={0: NS(key="shape"), 1: NS(key="qs_apply")})
    host = NS(children={0: live, 1: retired})
    main = NS(type="main", children={0: host}) if has_input_stage else host
    main.type = "main"
    state = {"_qs_open": builder_open, "entered_geometry": "preserved"}
    at = NS(
        _tree=NS(children={0: main}), session_state=NS(filtered_state=state), run=Mock(),
    )

    assert discard_retired_qs_fragment(at) is at
    assert host.children[0] is live
    assert (1 in host.children) is builder_open
    assert at.run.call_count == int(not has_input_stage and not builder_open)
    assert state == {"_qs_open": builder_open, "entered_geometry": "preserved"}
