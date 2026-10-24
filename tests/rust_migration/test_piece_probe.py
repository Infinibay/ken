"""The native source caller rejects answers and filesystem escapes before work."""
from copy import deepcopy
import hashlib,json,os,subprocess
from pathlib import Path
import pytest
from tools.rust_migration.piece_validate import FORMAT
ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def probe():
    path=Path(os.environ.get('KEN_SOURCE_PIECE_PROBE',ROOT/'target/debug/examples/source_piece_probe'))
    assert path.is_file(),'build the source_piece_probe example before its protocol gates'
    return path.resolve()
def request():return dict(format=FORMAT,resources=dict(ranking=None,static=None),cases=[dict(id='empty',family='catalog',kind='catalog',input=dict(files={},owners=[]))])
def execute(probe,tmp_path,value):
    return subprocess.run([str(probe)],input=json.dumps(value).encode(),capture_output=True,cwd=tmp_path,timeout=20)
def test_actual_native_empty_catalog_has_observations_and_measured_scope(probe,tmp_path):
    result=execute(probe,tmp_path,request());assert result.returncode==0,result.stderr.decode()
    value=json.loads(result.stdout);case=value['cases'][0]
    assert case['result']==dict(inventory=[],projections=[],lines={},hashes={})
    assert value['metrics']['max_rss_bytes']>0 and value['format']==FORMAT
@pytest.mark.parametrize('change',['root-answer','case-answer','input-answer','duplicate','unknown-family','unknown-kind','empty','resource-absolute','resource-parent','absolute-source'])
def test_untrusted_answers_and_escape_shapes_reject(probe,tmp_path,change):
    value=request()
    if change=='root-answer':value['expected']={}
    elif change=='case-answer':value['cases'][0]['result']={}
    elif change=='input-answer':value['cases'][0]['input']['expected']={}
    elif change=='duplicate':value['cases']*=2
    elif change=='unknown-family':value['cases'][0]['family']='shell'
    elif change=='unknown-kind':value['cases'][0]['kind']='exec'
    elif change=='empty':value['cases']=[]
    elif change=='resource-absolute':value['resources']['static']='/etc/passwd'
    elif change=='resource-parent':value['resources']['ranking']='../outside'
    else:
        outside=tmp_path/'outside.py';outside.write_bytes(b'unchanged')
        value['cases'][0]['input']['files']={str(outside):list(b'overwrite')}
    result=execute(probe,tmp_path,value)
    assert result.returncode!=0 or all('error'in c and 'result'not in c for c in json.loads(result.stdout)['cases'])
    if change=='absolute-source':assert outside.read_bytes()==b'unchanged'
def test_escape_observation_only_uses_its_owned_sibling_fixture(probe,tmp_path):
    value=request();content=b'outside fixture\n';key=dict(path='escape.py',kind='module',qualname=None,owner=None,definition_ordinal=0)
    span=dict(start_line=1,end_line=1)
    passage=dict(entity=key,span=span,entity_span=span,source_hash=hashlib.sha256(content).hexdigest(),language='python',role='definition',split_reason=None,signals={},implementation_start_line=None,fields={k:''for k in ('identity','signature','documentation','body','path')})
    value['cases'][0]['input']=dict(files={'../outside.py':list(content)},owners=[dict(key=key,passages=[passage])],symlinks=[dict(path='escape.py',target='../outside.py')])
    result=execute(probe,tmp_path,value);assert result.returncode==0,result.stderr.decode()
    assert json.loads(result.stdout)['cases'][0]['error']==dict(type='ValueError',message='source outside root')

def test_scenario_creation_and_mutations_never_follow_linked_parents(probe,tmp_path):
    # Every sentinel is owned by this regression's disposable pytest directory.
    links=[dict(path='a',target='.'),dict(path='b',target='a/..'),dict(path='c',target='b/..')]
    for operation in ('write','delete','symlink','create-link'):
        sentinel=tmp_path/'sentinel';sentinel.write_bytes(b'unchanged')
        physical=dict(files={},owners=[],symlinks=deepcopy(links))
        data=dict(catalog=physical,matches=[],piece_kind='file',query='source')
        if operation=='create-link':physical['symlinks'].append(dict(path='c/new-link',target='.'))
        else:data['mutation']=dict(op=operation,path='c/sentinel',bytes=list(b'changed'))
        value=request();value['cases']=[dict(id=operation,family='cards',kind='cards',input=data)]
        result=execute(probe,tmp_path,value)
        assert sentinel.is_file() and not sentinel.is_symlink() and sentinel.read_bytes()==b'unchanged',operation
        assert not(tmp_path/'new-link').exists() and not(tmp_path/'new-link').is_symlink()
        assert result.returncode!=0 or 'error'in json.loads(result.stdout)['cases'][0],operation
