"""Numeric families remain disjoint and tied to their actual original observers."""
import copy,json
from pathlib import Path
from tools.rust_migration.numeric_reference import definitions,validate_reference
ROOT=Path(__file__).resolve().parents[2]
def test_numeric_original_families_accept_only_their_complete_observations():
    for family,count in [('forest',318),('forest-edges',28),('stems',74),('alignment',245),('alignment-edges',22),('features',76),('features-edges',7),('features-math-edges',3),('owner-ranking',70)]:
        value=json.loads((ROOT/f'crates/ken-retrieval/tests/fixtures/numeric-reference-{family}.json').read_bytes())
        assert len(value['cases'])==count
        assert not validate_reference(value,family)
        for mutation in ['missing','order','result','observer','test']:
            changed=copy.deepcopy(value)
            if mutation=='missing':changed['cases'].pop()
            elif mutation=='order':changed['cases'].reverse()
            elif mutation=='result':changed['cases'][0]['result']={'omitted':True}
            elif mutation=='observer':changed['script_sha256']='0'*64
            else:changed['test_states'][0]['outcome']='skipped'
            assert validate_reference(changed,family),mutation

def test_numeric_requests_have_no_expected_output_and_have_distinct_wire_identities():
    ids=[]
    for family in ['forest','forest-edges','stems','alignment','alignment-edges','features','features-edges','features-math-edges','owner-ranking']:
        cases=definitions(family)
        assert all(set(c)=={'id','kind','input'}for c in cases)
        assert all('result'not in c['input']and 'expected'not in c['input']for c in cases)
        ids.extend((family,c['id'])for c in cases)
    assert len(ids)==len(set(ids))==843
