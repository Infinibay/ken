"""Index-history inputs stay independent of native results and cover every language."""
from pathlib import Path
from tools.rust_migration.index_scenarios import scenario_definitions,validate_scenario_reference
ROOT=Path(__file__).resolve().parents[2]
def test_history_definitions_are_input_only_complete_and_stable():
    cases=scenario_definitions(ROOT)
    assert len(cases)>=10 and cases==scenario_definitions(ROOT)
    assert len({c['id']for c in cases})==len(cases)
    assert all(set(c)=={'id','operations'}for c in cases)
    labels={c['id'].split(':')[0]for c in cases}
    assert {'mixed','languages','header-errors','profile-lexical','profile-actual-tokenizer','encoding-failure','source-race','profile-race','nonfinite-behavior','mapped-chunks','inline-fallback','workload-100'}<=labels
    assert not any('expected'in op for c in cases for op in c['operations'])
def test_incomplete_or_fabricated_original_histories_reject():
    assert validate_scenario_reference({})
    assert validate_scenario_reference(None)
def test_original_document_batches_follow_the_requested_chunk_boundaries():
    from tools.rust_migration.index_scenarios import validate_document_chunks
    definition={'operations':[dict(op='index',paths=['a.py','b.py','c.py','d.py','e.py'],embed=True,chunk_files=2)]}
    case={'steps':[{'result':{'events':[[p,'indexed']for p in definition['operations'][0]['paths']],'encoder_calls':[['one wrong batch']]}}]}
    assert validate_document_chunks(definition,case)
    case['steps'][0]['result']['encoder_calls']=[['a','b'],['c','d'],['e']]
    assert validate_document_chunks(definition,case)==[]
