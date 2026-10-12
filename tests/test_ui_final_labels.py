"""Keep presentation labels separate from retained quantities and user text."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
APP = Path(__file__).resolve().parents[1] / 'app' / 'sector_app.py'

def _tree():
    return ast.parse(APP.read_text(encoding='utf-8'))

@pytest.mark.parametrize('value,expected', [('mild','Reinforcing steel'),('prestress','Prestressing steel'),(None,''),('', ''),('user_f_ck_$<b>','user_f_ck_$<b>'),('MILD','MILD')])
def test_material_kind_names_only_exact_controlled_values(value,expected):
    fn=next(n for n in _tree().body if isinstance(n,ast.FunctionDef) and n.name=='_ui_material_kind')
    ns={};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(APP),'exec'),ns)
    assert ns[fn.name](value)==expected

@pytest.mark.parametrize('prefix,operands', [
 ('Common member angle:', ['1.250','2.500','-3.000']),
 ('$M_{Ed,total}', ['-1.000','2.000','3.000','4.000','5.000']),
 ('Concrete carries the shear (', ['0.0','4.0']),
 ('Torsional cracking inputs:', ['1.200','1.500','0.800']),
 ('Compound section (6.3.1(3)):', []),
 ('Governing sub-tube resistance component:', ['125.0%']),
])
def test_authored_math_captions_keep_substitutions_and_balanced_spans(prefix,operands):
    ns={'cr':{'cot':1.25,'trd_max':2.5,'vrd_max':-3.},'lg':{'m_ed':-1.,'mv':2.,'mt':3.,'m_total':4.,'m_rd':5.},'concrete':{'angle_valid':True},'tr':{'v_ed':0.,'vrd_c':4.},'t':{'fctk_005':1.2,'gamma_ct':1.5,'fctd':.8,'method':'literal_$method'},'viz':SimpleNamespace(chord_angle_note=lambda *a,**k:'retained angle note'),'_THETA':'\u03b8','angle_clause':'retained angle clause','gov_lbl':'literal_part','util_txt':'125.0%'}
    found=[]
    for n in ast.walk(_tree()):
        if not (isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='caption' and n.args):continue
        source=''.join(c.value for c in ast.walk(n.args[0]) if isinstance(c,ast.Constant) and isinstance(c.value,str))
        if not source.startswith(prefix):continue
        value=eval(compile(ast.Expression(n.args[0]),str(APP),'eval'),ns)
        if value.startswith(prefix):found.append(value)
    assert len(found)==1,found
    text=found[0];assert text.replace('literal_$method','literal_method').count('$')%2==0
    for operand in operands:assert operand in text
    if prefix.startswith('Governing'):assert '$ = 125.0%' in text
