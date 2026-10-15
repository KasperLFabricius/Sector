"""Pure count contract checks, with native registration reserved for root."""
import ast
import os
from pathlib import Path
import sys
import pytest

# Prepared outside-WT replay requires explicit paths; applied tests use their checkout.
WT=Path(os.environ.get('SECTOR_TORSION_CONTRACT_REPOSITORY',str(Path(__file__).resolve().parents[1]))).resolve()
SOURCE=Path(os.environ.get('SECTOR_TORSION_CONTRACT_SOURCE',str(WT/'app/sector_app.py'))).resolve()
assert (WT/'app/project_io.py').is_file()
assert SOURCE.is_file()
sys.path.insert(0,str(WT))
sys.path.insert(0,str(WT/'app'))
import project_io
import input_stage_host


def call():
    matches=[n for n in ast.walk(ast.parse(SOURCE.read_text(encoding='utf-8-sig'))) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_seeded_number' and len(n.args)>6 and isinstance(n.args[6],ast.Constant) and n.args[6].value=='torsion_nsub']
    assert len(matches)==1
    return matches[0]


def test_count_widget_contract_is_integral_and_keeps_bounds_default_step():
    values=[ast.literal_eval(n) for n in call().args[2:6]]
    assert values==[2,4,2,1]
    assert all(type(v) is int for v in values)


@pytest.mark.parametrize('value',[2,3,4,2.0,3.0,4.0])
def test_saved_current_and_legacy_counts_seed_exact_integral_widget(value):
    canonical=project_io._canonical_scalars({'torsion_nsub':value},{})
    retained=canonical['torsion_nsub']
    assert type(retained) is int
    assert retained==value
    values=[ast.literal_eval(n) for n in call().args[2:6]]
    args,kwargs=input_stage_host._seed_arguments('number_input',('Number of sub-rectangles',values[0],values[1]),{'step':values[3],'key':'torsion_nsub'},retained)
    assert args==('Number of sub-rectangles',2,4)
    assert kwargs['value']==retained
    assert all(type(v) is int for v in (args[1],args[2],kwargs['value'],kwargs['step']))
    assert list(range(int(kwargs['value'])))==list(range(int(value)))


@pytest.mark.parametrize('value',[True,'2',2.5,float('nan'),float('inf'),[],{}])
def test_invalid_count_stays_rejected_by_original_decoder(value):
    with pytest.raises(project_io.ProjectInputError):
        project_io._canonical_scalars({'torsion_nsub':value},{})
