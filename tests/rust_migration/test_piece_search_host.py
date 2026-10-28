from pathlib import Path
import json,os,shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_piece_search_missing_capture_rejects_summary(tmp_path):
    from tools.rust_migration.piece_search_host import verify_capture
    (tmp_path/'summary.json').write_text('{"passed":true}');assert verify_capture(tmp_path,ROOT)

def test_symbol_probe_rejects_answers_empty_cases_and_foreign_physical_inputs(tmp_path):
    from tools.rust_migration.piece_search_host import reference,request
    root=tmp_path;binary=ROOT/'target/debug/examples/piece_search_probe';value=request(ROOT,reference(ROOT),root)
    value['cases']=value['cases'][:1]
    value.update(grammar_manifest=os.environ['KEN_GRAMMAR_MANIFEST'],source=os.environ['KEN_ETTIN_SOURCE'],library=os.environ['KEN_ORT_LIBRARY'])
    def run(v):return subprocess.run([binary],input=json.dumps(v),text=True,capture_output=True)
    result=run(value);assert result.returncode==0,result.stderr
    assert run(value|dict(expected={})).returncode!=0
    assert run(value|dict(cases=[])).returncode!=0
    assert run(value|dict(cases=[value['cases'][0]|dict(observations=[])])).returncode!=0
    bad=json.loads(json.dumps(value));bad['cases'][0]['input']['physical']['expected']=[];assert run(bad).returncode!=0

@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_PIECE_SEARCH_PACKET',ROOT/'.ken/rust-migration/piece-search/packet'))
    out=tmp_path/'packet';shutil.copytree(source,out);return out

def test_actual_piece_search_is_native_and_source_bound(packet):
    from tools.rust_migration.piece_search_host import verify_capture
    assert not verify_capture(packet,ROOT)

@pytest.mark.parametrize('change',['input-answer','rank','witness','cache','calls','scores','binary','grammar','original','parent','real-score','real-details'])
def test_resealed_piece_search_capture_rejects(packet,change):
    from tools.rust_migration.piece_search_host import verify_capture
    from tools.rust_migration.native_json import identity
    assert not verify_capture(packet,ROOT)
    out=packet/'piece-search';capture=out/'native';execution=capture/'execution.json';record=json.loads(execution.read_bytes())
    if change=='input-answer':
        p=capture/'inputs.json';v=json.loads(p.read_bytes());v['expected']={};p.write_text(json.dumps(v));record['request_sha256']=identity(p)['sha256']
    elif change in('real-score','real-details'):
        p=capture/'stdout.json';v=json.loads(p.read_bytes());obs=next(c for c in v['cases']if c['id']=='real-symbol')['observations'][0]
        signals=obs['result']['results'][0]['signals']
        if change=='real-score':signals['neural_score']+=100
        else:signals['reranker']=None
        p.write_text(json.dumps(v));record['stdout_sha256']=identity(p)['sha256']
    elif change in('rank','witness','cache','calls','scores'):
        p=capture/'stdout.json';v=json.loads(p.read_bytes());obs=v['cases'][0]['observations'][0]
        if change=='rank':obs['result']['results'].reverse()
        elif change=='witness':obs['result']['results'][0]['entity']['qualname']='invented'
        elif change=='cache':obs['cache'][0]['source_hash']='0'*64
        elif change=='calls':obs['calls']=[]
        else:obs['result']['results'][0]['source_hash']='foreign'
        p.write_text(json.dumps(v));record['stdout_sha256']=identity(p)['sha256']
    elif change=='binary':(out/'bin/piece_search_probe').write_bytes(b'changed')
    elif change=='grammar':(out/'grammar-manifest').write_text('{}')
    elif change=='original':(out/'ORIGINAL.json.gz').write_bytes(b'changed')
    else:(packet/'symbol-ranking/native/execution.json').unlink()
    execution.write_text(json.dumps(record));assert verify_capture(packet,ROOT)
