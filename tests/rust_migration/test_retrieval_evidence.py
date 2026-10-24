"""Tamper checks use actual process evidence; synthetic gate samples are unit inputs."""
import json,os,shutil,sys,tarfile,xml.etree.ElementTree as ET
from pathlib import Path
import pytest
from tools.rust_migration.native_json import load,identity
from tools.rust_migration.retrieval_evidence import verify_capture,verify_gates,verify_original,verify_review,RUST_ROOTS,PYTHON_ROOTS
ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    value=os.environ.get('KEN_RETRIEVAL_EVIDENCE_ROOT')
    if value:return Path(value)
    root=tmp_path_factory.mktemp('retrieval-capture');system='macos'if sys.platform=='darwin'else'linux'
    with tarfile.open(ROOT/f'docs/validation/rust-migration-2026-10-23/m4-kernels-review/{system}-capture.tar.gz')as archive:archive.extractall(root,filter='data')
    with tarfile.open(ROOT/'docs/validation/rust-migration-2026-10-23/m4-kernels-review/sources.tar.gz')as archive:
        archive.extractall(root,members=[m for m in archive.getmembers() if m.name.startswith('native-sources/')],filter='data')
    return root

def test_actual_complete_native_kernel_capture_passes(capture):
    assert not verify_capture(capture/'native',load(capture/'original/reference.json'))

def test_actual_supplemental_review_regressions_pass(capture):
    assert verify_review(capture,ROOT,'macos'if sys.platform=='darwin'else'linux',snapshot=capture/'native-sources')

@pytest.mark.parametrize('mutation',['request','runtime','result','original'])
def test_supplemental_proof_rejects_resealed_changes(capture,tmp_path,mutation):
    out=tmp_path/'review';out.mkdir()
    for name in ('native-review','original-review'):shutil.copytree(capture/name,out/name)
    if mutation=='original':p=out/'original-review/observations.json';p.write_bytes(p.read_bytes()+b' ')
    else:
        base=out/'native-review';p=base/('inputs.json'if mutation=='request'else'execution.json'if mutation=='runtime'else'stdout.json');v=load(p)
        if mutation=='request':v['cases'].pop()
        elif mutation=='runtime':v['owned_before']['dense-blas/forged']={'bytes':1,'sha256':'0'*64};v['owned_after']=v['owned_before']
        else:v['cases'][-1]['result'][0]['passages'].reverse()
        p.write_text(json.dumps(v))
        if mutation!='runtime':e=load(base/'execution.json');e['request_sha256'if mutation=='request'else'stdout_sha256']=identity(p)['sha256'];(base/'execution.json').write_text(json.dumps(e))
    with pytest.raises((ValueError,KeyError,TypeError)):verify_review(out,ROOT,'macos'if sys.platform=='darwin'else'linux',snapshot=capture/'native-sources')

@pytest.mark.parametrize('mutation',['stdout','request','source','binary','loader','summary','rss','platform','owner','evidence','input_expected'])
def test_resealed_native_kernel_capture_rejects_changed_proof(capture,tmp_path,mutation):
    out=tmp_path/'native';shutil.copytree(capture/'native',out);reference=load(capture/'original/reference.json');pinned=load(capture/'native/SOURCES.json')
    if mutation=='loader':(out/'stderr.log').write_text('libpython.so')
    elif mutation in('source','binary'):
        p=out/'BUILD.json';v=load(p)
        if mutation=='source':v['sources']['Cargo.lock']['sha256']='0'*64
        else:v['native_sha256']='0'*64
        p.write_text(json.dumps(v))
    elif mutation=='summary':p=out/'execution.json';v=load(p);v['passed']=True;p.write_text(json.dumps(v))
    else:
        file='inputs.json'if mutation in('request','input_expected')else'stdout.json';p=out/file;v=load(p)
        if mutation in('stdout','request'):v['cases'].pop()
        elif mutation=='input_expected':v['cases'][0]['expected']={}
        elif mutation=='rss':v['metrics']['max_rss_bytes']=0
        elif mutation=='platform':v['platform']='other'
        else:
            result=next(c['result']for c in v['cases']if c['kind']=='dense'and c.get('result'))
            if mutation=='owner':result[0]['entity']['qualname']='forged'
            else:result[0]['passages'].pop()
        p.write_text(json.dumps(v));e=load(out/'execution.json');e['request_sha256'if file=='inputs.json'else'stdout_sha256']=identity(p)['sha256'];(out/'execution.json').write_text(json.dumps(e))
    assert verify_capture(out,reference,pinned)

@pytest.fixture
def gate_sample(tmp_path):
    """Synthetic unit data, never accepted as platform execution evidence."""
    g=tmp_path/'synthetic-gates';g.mkdir();rust=['synthetic_'+str(i)for i in range(RUST_ROOTS)]
    (g/'rust-list.log').write_text('\n'.join(n+': test'for n in rust));(g/'rust-tests.log').write_text('\n'.join('test '+n+' ... ok'for n in rust)+f'\ntest result: ok. {RUST_ROOTS} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
    names=['synthetic_'+str(i)for i in range(PYTHON_ROOTS)];(g/'python-list.log').write_text('\n'.join('tests/rust_migration/test_retrieval_evidence.py::'+n for n in names));xml=ET.Element('testsuite')
    for n in names:ET.SubElement(xml,'testcase',classname='tests.rust_migration.test_retrieval_evidence',name=n)
    ET.ElementTree(xml).write(g/'python.xml');(g/'fmt.log').write_bytes(b'');(g/'clippy.log').write_text('Finished `dev` profile');return g

def test_complete_gate_helper_passes(gate_sample):assert not verify_gates(gate_sample)

@pytest.mark.parametrize('mutation',['omit','skip','rust','fmt','clippy','raw'])
def test_changed_or_skipped_raw_gates_reject(gate_sample,tmp_path,mutation):
    g=tmp_path/'gates';shutil.copytree(gate_sample,g)
    if mutation=='omit':p=g/'python-list.log';p.write_text('\n'.join(p.read_text().splitlines()[1:]))
    elif mutation=='skip':p=g/'python.xml';xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
    elif mutation=='rust':p=g/'rust-tests.log';p.write_text(p.read_text().replace('... ok','... FAILED',1))
    elif mutation=='fmt':(g/'fmt.log').write_text('source format differs')
    elif mutation=='clippy':(g/'clippy.log').write_text('error: failed')
    else:(g/'python.xml').write_text('<testsuites/>')
    assert verify_gates(g)

def test_actual_original_kernel_capture_passes(capture):
    assert verify_original(capture/'original',ROOT,'macos'if sys.platform=='darwin'else'linux')

@pytest.mark.parametrize('mutation',['owner','case','xml','raw'])
def test_changed_original_observations_or_execution_rejects(capture,tmp_path,mutation):
    root=tmp_path/'original';shutil.copytree(capture/'original',root)
    if mutation=='raw':p=root/'stdout.log';p.write_bytes(p.read_bytes()+b'forged')
    elif mutation=='xml':p=root/'original-tests.xml';xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
    else:
        p=root/'reference.json';v=load(p)
        if mutation=='owner':v['owners'][next(iter(v['owners']))]='0'*64
        else:v['cases'].pop()
        p.write_text(json.dumps(v))
    with pytest.raises((ValueError,KeyError,TypeError)):verify_original(root,ROOT,'macos'if sys.platform=='darwin'else'linux')
