"""Import acceptance retains every complete edge in input and project modes."""
from copy import deepcopy
from pathlib import Path
import pytest
from tools.rust_migration.import_validate import import_cases, compare_import_observations, source_identity
REPO=Path(__file__).resolve().parents[2]

@pytest.fixture
def cases():return import_cases(REPO)

def observed(cases):
    rows=[]
    for row in cases:
        for mode in ('inputs','project'):
            if 'error'in row:
                error=dict(kind='invalid_config',path=next(iter(row['input']['configs'])),reason='invalid config shape')
                rows.append(dict(id=mode+':'+row['id'],error=error))
            else:rows.append(dict(id=mode+':'+row['id'],results=deepcopy(row['results'])))
    return dict(format='ken-import-observation/1',cases=rows)

def test_complete_original_inventory_and_both_native_modes(cases):
    assert len(cases)==91 and sum(len(c['input']['imports'])for c in cases)==92
    assert len([c for c in cases if'error'in c])==2
    assert compare_import_observations(cases,observed(cases))==[]

@pytest.mark.parametrize('mutation',['missing','duplicate','reorder','target','classification','error','success','format'])
def test_changed_or_lost_edges_and_failures_are_rejected(cases,mutation):
    actual=observed(cases);rows=actual['cases']
    if mutation=='missing':rows.pop()
    elif mutation=='duplicate':rows[-1]=deepcopy(rows[0])
    elif mutation=='reorder':rows[0],rows[1]=rows[1],rows[0]
    elif mutation in ('target','classification'):
        result=next(r['results'][0]for r in rows if r.get('results'))
        result['target'if mutation=='target'else'resolution']='changed'
    elif mutation=='error':next(r for r in rows if'error'in r)['error']['kind']='other'
    elif mutation=='success':
        row=next(r for r in rows if'error'in r);row.pop('error');row['results']=[]
    else:actual['format']='other'
    assert compare_import_observations(cases,actual)

def test_source_identity_includes_input_assets_and_actual_filesystem_owner():
    sources=source_identity(REPO)
    assert 'crates/ken-core/tests/fixtures/import-alias-surrogates.json'in sources
    assert 'crates/ken-core/src/imports/project_inputs.rs'in sources
