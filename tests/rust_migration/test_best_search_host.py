from pathlib import Path
import copy,json,os,shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_best_search_missing_capture_rejects_a_passing_summary(tmp_path):
    from tools.rust_migration.best_search_host import verify_capture
    (tmp_path/'summary.json').write_text('{"passed":true}');assert verify_capture(tmp_path,ROOT)

def test_input_only_endpoint_and_preparation_probes_reject_answers(tmp_path):
    from tools.rust_migration.best_search_host import originals,request,preparation_request
    best,prep=originals(ROOT)
    values=[('best_search_probe',request(ROOT,best,tmp_path)),('context_preparation_probe',preparation_request(prep))]
    for name,value in values:
        value['cases']=value['cases'][:1]
        if name=='best_search_probe':
            value.update(grammar_manifest=os.environ['KEN_GRAMMAR_MANIFEST'],ranking_directory=str(ROOT/'crates/ken-retrieval/resources/ranking'),library=os.environ['KEN_ORT_LIBRARY'])
            Path(value['cache_parent']).mkdir()
        def run(v):return subprocess.run([ROOT/'target/debug/examples'/name],input=json.dumps(v),text=True,capture_output=True)
        result=run(value);assert result.returncode==0,result.stderr
        assert run(value|dict(expected={})).returncode!=0
        assert run(value|dict(cases=[])).returncode!=0
        assert run(value|dict(cases=[value['cases'][0]|dict(events=[])])).returncode!=0
        bad=copy.deepcopy(value);bad['cases'][0]['input']['expected']=[];assert run(bad).returncode!=0

@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_BEST_SEARCH_PACKET',ROOT/'.ken/rust-migration/best-search/packet'))
    out=tmp_path/'packet';shutil.copytree(source,out);return out

def test_complete_best_search_packet_is_native_and_source_bound(packet):
    from tools.rust_migration.best_search_host import verify_capture
    assert not verify_capture(packet,ROOT)

@pytest.mark.parametrize('change',['answer','generation','database','lru','calls','source','real-score','real-details','word-profile','artifact','mapped','readonly','cache','blas','source-resource','rank-resource','grammar','binary','original','parent'])
def test_resealed_best_search_and_preparation_capture_rejects_tampering(packet,change):
    from tools.rust_migration.best_search_host import verify_capture
    from tools.rust_migration.native_json import identity
    assert not verify_capture(packet,ROOT)
    out=packet/'best-search';capture=out/('preparation'if change in('artifact','mapped','readonly','cache')else'native');record=json.loads((capture/'execution.json').read_bytes())
    if change=='answer':
        p=capture/'inputs.json';v=json.loads(p.read_bytes());v['cases'][0]['input']['expected']={};p.write_text(json.dumps(v));record['request_sha256']=identity(p)['sha256']
    elif change in('blas','source-resource','rank-resource'):
        prefix={'blas':'dense-blas/','source-resource':'sources/','rank-resource':'ranking/'}[change]
        name=next(n for n in record['owned_before']if n.startswith(prefix));del record['owned_before'][name];del record['owned_after'][name]
    elif change in('grammar','binary','original'):
        path={'grammar':out/'grammar-manifest','binary':out/'bin/best_search_probe','original':out/'ORIGINAL.json.gz'}[change];path.write_bytes(b'changed')
    elif change=='parent':(packet/'piece-search/native/execution.json').unlink()
    else:
        p=capture/'stdout.json';v=json.loads(p.read_bytes());rows={r['id']:r for r in v['cases']}
        if change in('artifact','mapped','readonly','cache'):
            event=rows['cold-warm-generation']['events'][0]
            if change=='artifact':next(iter(event['state']['snapshots'].values()))['full.npy']['sha256']='0'*64
            elif change=='cache':event['state']['cache']=[]
            elif change=='mapped':event['result']['mapped_views']=False
            else:event['result']['pool']['readonly']=False
        else:
            event=rows['contextual-symbol']['events'][0]
            if change=='generation':event['state']['prepared'][0]['generation']+=1
            elif change=='database':event['state']['prepared'][0]['database']='foreign'
            elif change=='lru':rows['prepared-project-lru-two']['events'][1]['state']['prepared'].reverse()
            elif change=='calls':event['calls']=[]
            elif change=='source':event['result']['results'][0]['source_hash']='foreign'
            elif change=='word-profile':rows['registered-symbol']['events'][0]['result']['profile_version']='0'*64
            elif change=='real-score':rows['registered-symbol']['events'][0]['result']['results'][0]['signals']['neural_score']+=100
            else:rows['registered-symbol']['events'][0]['result']['results'][0]['signals']['reranker']=None
        p.write_text(json.dumps(v));record['stdout_sha256']=identity(p)['sha256']
    (capture/'execution.json').write_text(json.dumps(record));assert verify_capture(packet,ROOT)

def test_confined_complete_probes_authenticate_their_dense_runtime(tmp_path):
    from tools.rust_migration.best_search_host import capture_native,originals,compare,compare_preparation,verify_endpoints
    from tools.rust_migration.native_json import load
    from tools.rust_migration.retrieval_validate import runtime_files
    best,prep=originals(ROOT);capture_native(ROOT,best,prep,tmp_path)
    for name in('native','preparation'):
        execution=load(tmp_path/name/'execution.json')
        for filename,row in runtime_files(ROOT,'x86_64').items():assert execution['owned_before']['dense-blas/'+filename]==row
    core=load(tmp_path/'native/stdout.json')['runtime']
    assert not compare(best,load(tmp_path/'native/stdout.json'),core)
    assert not compare_preparation(prep,load(tmp_path/'preparation/stdout.json'))
    assert not verify_endpoints(tmp_path,ROOT)
