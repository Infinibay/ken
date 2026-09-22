import pytest

from ken.kql2.service import search
from ken.kql2.compiler import CompileError

QUERY = '''language "kql/2"; module t; query q {
 callable $f { name: "f"; body {
   var $y { name: "y"; }
   gap until next { forbid write(binding($y)); }
   where $y.name == "y";
   $y = $y + 1;
   return $y;
 } } select $f.name;
}'''


def run(tmp_path,source,query=QUERY):
    (tmp_path/'a.py').write_text(source)
    return search(tmp_path,query,cache_mb=0)


@pytest.mark.parametrize('noise,expected', [
    ('print("noise")',True),
    ('pass',True),
    ('y=0',False),
    ('y=2',False),
    ('z=2',True),
])
def test_gap_protects_binding_and_excludes_endpoint_write(tmp_path,noise,expected):
    source = 'def f():\n y=0\n '+noise+'\n y=y+1\n return y\n'
    assert bool(run(tmp_path,source)['rows']) is expected


def test_all_paths_not_only_the_clean_witness(tmp_path):
    result = run(tmp_path,'def f(flag):\n y=0\n if flag:\n  y=3\n y=y+1\n return y\n')
    assert result['rows'] == []


def test_nonconnecting_return_branch_not_in_interval(tmp_path):
    result = run(tmp_path,'def f(flag):\n y=0\n if flag:\n  y=3\n  return 0\n y=y+1\n return y\n')
    assert result['rows'] == [['f']]


def test_reference_or_dynamic_write_inventory_remains_unknown(tmp_path):
    result = run(tmp_path,'def f():\n y=0\n exec("y=3")\n y=y+1\n return y\n')
    assert result['rows'] == [] and result['unknown_candidates'] > 0


def test_modification_after_gap_endpoint_is_permitted(tmp_path):
    result = run(tmp_path,'def f():\n y=0\n y=y+1\n y=8\n return y\n')
    assert result['rows'] == [['f']]


@pytest.mark.parametrize('body', [
    'gap until next { forbid write(binding($y)); } var $y {} return $y;',
    'var $y {} gap until next { forbid write(binding($y)); }',
    'var $y {} gap until next { forbid write(binding($missing)); } return $y;',
])
def test_invalid_gap_anchors_and_scope(tmp_path,body):
    with pytest.raises(CompileError):
        search(tmp_path,'language "kql/2"; module t; query q { callable $f { body {'+body+'} } select $f; }')
