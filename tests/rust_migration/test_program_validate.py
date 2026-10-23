"""Complete program observations cannot be replaced by counts or partial matches."""
from copy import deepcopy
from pathlib import Path
import pytest
from tools.rust_migration.program_validate import program_cases,compare_program_observations,requests,source_identity
REPO=Path(__file__).resolve().parents[2]

def expected_observations(cases):
 def error():return dict(error=dict(kind='invalid_program',message='invalid original program'))
 rows=[]
 for case in cases:
  result=dict(id=case['id']);expected=case['expected']
  if case['kind']=='type':result['descriptor']=deepcopy(expected['result'])
  elif'error'in expected:result.update(error())
  else:
   result['program']=deepcopy(expected['result'])
   if case['kind']=='normalize':
    result['bodies']=deepcopy(expected['bodies']);result['lookups']=[]
    for lookup in expected['lookups']:
     result['lookups'].append({**{k:lookup[k]for k in ('name','scope','point')},**(error()if'error'in lookup else dict(result=deepcopy(lookup['result'])))})
  rows.append(result)
 return dict(format='ken-program-observation/1',cases=rows)

def test_full_corpus_original_errors_and_input_only_requests():
 cases=program_cases(REPO)
 assert len(cases)==320 and len({c['id']for c in cases})==320
 assert sum('error'in c['expected']for c in cases)==14
 assert compare_program_observations(cases,expected_observations(cases))==[]
 request=requests(cases)
 assert all('expected'not in row for row in request['cases'])
 assert 'crates/ken-program/src/environment.rs'in source_identity(REPO)

@pytest.mark.parametrize('mutation',['missing','duplicate','reorder','node','scope','symbol','reference','body','lookup','error','format'])
def test_changed_or_lost_complete_semantics_are_rejected(mutation):
 cases=program_cases(REPO);actual=expected_observations(cases);rows=actual['cases']
 row=next(r for r in rows if r.get('program',{}).get('symbols')and r['program']['references'])
 if mutation=='missing':rows.pop()
 elif mutation=='duplicate':rows[-1]=deepcopy(rows[0])
 elif mutation=='reorder':rows[0],rows[1]=rows[1],rows[0]
 elif mutation in ('node','scope','symbol','reference'):
  key={'node':'nodes','scope':'scopes','symbol':'symbols','reference':'references'}[mutation];row['program'][key].pop()
 elif mutation=='body':next(r['bodies']for r in rows if r.get('bodies')).pop()
 elif mutation=='lookup':next(r['lookups']for r in rows if r.get('lookups')).pop()
 elif mutation=='error':next(r for r in rows if'error'in r)['error']['kind']='other'
 else:actual['format']='other'
 assert compare_program_observations(cases,actual)
