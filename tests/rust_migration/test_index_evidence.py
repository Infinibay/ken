"""Tamper checks consume actual archived process evidence, not synthetic execution."""
import hashlib,json,os,shutil,tarfile
from pathlib import Path
import pytest
from tools.rust_migration.native_json import load,identity
from tools.rust_migration.index_evidence import verify_index_capture,verify_index_gates,verify_original_capture
REPO=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    supplied=os.environ.get('KEN_INDEX_EVIDENCE_ROOT')
    if supplied:return Path(supplied)
    import sys
    root=tmp_path_factory.mktemp('index-evidence');system='macos'if sys.platform=='darwin'else'linux'
    with tarfile.open(REPO/f'docs/validation/rust-migration-2026-10-23/m3-index/{system}-capture.tar.gz')as archive:archive.extractall(root,filter='data')
    return root

def test_actual_native_complete_capture_passes(capture):
    reference=load(capture/'original/scenario-reference.json')
    assert not verify_index_capture(capture/'native',reference)

@pytest.mark.parametrize('mutation',['output','missing','request','source','binary','summary','loader','rss','platform','owner','projection'])
def test_resealed_index_capture_rejects_tampering(capture,tmp_path,mutation):
    out=tmp_path/'native';shutil.copytree(capture/'native',out);reference=load(capture/'original/scenario-reference.json')
    if mutation=='loader':(out/'stderr.log').write_text('libpython.so')
    elif mutation in ['source','binary']:
        p=out/'BUILD.json';v=load(p)
        if mutation=='source':v['sources']['Cargo.lock']['sha256']='0'*64
        else:v['native_sha256']='0'*64
        p.write_text(json.dumps(v))
    elif mutation=='summary':
        p=out/'execution.json';v=load(p);v['passed']=True;p.write_text(json.dumps(v))
    else:
        file='inputs.json'if mutation=='request'else'stdout.json';p=out/file;v=load(p)
        if mutation=='request':v['cases'][0]['expected']={}
        elif mutation=='missing':v['cases'].pop()
        elif mutation=='rss':v['metrics']['max_rss_bytes']=0
        elif mutation=='platform':v['platform']='other'
        else:
            steps=[s for c in v['cases']for s in c['steps']]
            if mutation=='projection':next(s for s in steps if s['snapshot']['tables']['ci_passage_vectors'])['snapshot']['tables']['ci_passage_vectors'][0][2]='wrong'
            elif mutation=='owner':next(s for s in steps if s['snapshot']['tables']['ci_passages'])['snapshot']['tables']['ci_passages'][0][1]=999
            else:next(s for s in steps if 'result'in s)['result']['events']=[['forged','indexed']]
        p.write_text(json.dumps(v));e=load(out/'execution.json');e['request_sha256'if mutation=='request'else'stdout_sha256']=identity(p)['sha256'];(out/'execution.json').write_text(json.dumps(e))
    assert verify_index_capture(out,reference)

@pytest.mark.parametrize('mutation',['skip','omit','fmt','clippy','rust','xml'])
def test_index_gate_tampering_rejects(gate_sample,tmp_path,mutation):
    gates=tmp_path/'gates';shutil.copytree(gate_sample,gates)
    if mutation=='skip':
        import xml.etree.ElementTree as ET
        p=gates/'python.xml';xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
    elif mutation=='omit':p=gates/'python-list.log';p.write_text('\n'.join(p.read_text().splitlines()[1:]))
    elif mutation=='fmt':(gates/'fmt.log').write_text('Diff in source')
    elif mutation=='clippy':(gates/'clippy.log').write_text('error: failed')
    elif mutation=='rust':p=gates/'rust-tests.log';p.write_text(p.read_text().replace('... ok','... FAILED',1))
    else:(gates/'python.xml').write_text('<testsuites/>')
    assert verify_index_gates(gates)

def test_complete_index_gates_pass(gate_sample):
    assert not verify_index_gates(gate_sample)

@pytest.fixture
def gate_sample(tmp_path):
    """Synthetic verifier unit inputs; never credited as execution evidence."""
    import xml.etree.ElementTree as ET
    root=tmp_path/'synthetic-gates';root.mkdir()
    names=['synthetic_case_'+str(i)for i in range(43)]
    (root/'rust-list.log').write_text('\n'.join(n+': test'for n in names))
    (root/'rust-tests.log').write_text('\n'.join('test '+n+' ... ok'for n in names)+'\ntest result: ok. 43 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
    names=['synthetic_'+str(i)for i in range(43)]
    (root/'python-list.log').write_text('\n'.join('tests/rust_migration/test_index_evidence.py::'+n for n in names))
    xml=ET.Element('testsuite')
    for n in names:ET.SubElement(xml,'testcase',classname='tests.rust_migration.test_index_evidence',name=n)
    ET.ElementTree(xml).write(root/'python.xml')
    (root/'fmt.log').write_bytes(b'');(root/'clippy.log').write_text('Finished `dev` profile')
    return root

def test_actual_original_boundaries_and_suites_pass(capture):
    import sys
    assert verify_original_capture(capture/'original',REPO,REPO,'macos'if sys.platform=='darwin'else'linux')

@pytest.mark.parametrize('mutation',['owners','projection','projection_vector','original_xml','raw'])
def test_changed_original_observations_or_raw_tests_reject(capture,tmp_path,mutation):
    import sys,xml.etree.ElementTree as ET
    root=tmp_path/'original';shutil.copytree(capture/'original',root)
    if mutation=='raw':p=root/'stdout';p.write_bytes(p.read_bytes()+b'forged')
    elif mutation=='original_xml':
        p=root/'original-source.xml';xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
    else:
        p=root/('source-reference.json'if mutation=='owners'else'projection-reference.json');v=load(p)
        if mutation=='owners':v['owners'][next(iter(v['owners']))]='0'*64
        elif mutation=='projection':v['cases'].pop()
        else:v['cases'][0]['result']['tables']['ci_retrieval_embeddings'][0][5]={'blob_hex':'00'*12}
        p.write_text(json.dumps(v))
    with pytest.raises((ValueError,KeyError,TypeError)):
        verify_original_capture(root,REPO,REPO,'macos'if sys.platform=='darwin'else'linux')
