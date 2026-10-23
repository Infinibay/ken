"""Tamper checks bind actual original executions, native resources and raw results."""
import json,os,shutil,sys,tarfile,xml.etree.ElementTree as ET
from pathlib import Path
import pytest
from tools.rust_migration.native_json import load,identity
from tools.rust_migration.numeric_evidence import verify_original,verify_capture,verify_gates,RUST_ROOTS,PYTHON_ROOTS
ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    root=os.environ.get('KEN_NUMERIC_EVIDENCE_ROOT')
    if root:return Path(root)
    root=tmp_path_factory.mktemp('numeric-evidence');system='macos'if sys.platform=='darwin'else'linux'
    with tarfile.open(ROOT/f'docs/validation/rust-migration-2026-10-23/m4-numeric-owner/{system}-capture.tar.gz')as archive:archive.extractall(root,filter='data')
    return root
def test_actual_original_and_native_numeric_captures_pass(capture):
    reference=verify_original(capture/'original',ROOT,'macos'if sys.platform=='darwin'else'linux')
    assert not verify_capture(capture/'native',reference)
@pytest.mark.parametrize('change',['request','result','source','binary','runtime','resource','rows','names','calls','original','skipped'])
def test_changed_or_resealed_numeric_proof_rejects(capture,tmp_path,change):
    system='macos'if sys.platform=='darwin'else'linux';reference=verify_original(capture/'original',ROOT,system)
    if change in('original','skipped'):
        out=tmp_path/'original';shutil.copytree(capture/'original',out);p=out/'features'/'observations.json'if change=='original'else out/'features'/'original-tests.xml'
        if change=='original':p.write_bytes(p.read_bytes()+b' ')
        else:
            xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
        with pytest.raises((ValueError,KeyError,TypeError)):verify_original(out,ROOT,system)
        return
    out=tmp_path/'native';shutil.copytree(capture/'native',out);sources=load(out/'SOURCES.json')
    if change in('source','binary'):
        p=out/'BUILD.json';v=load(p)
        if change=='source':v['sources']['Cargo.lock']['sha256']='0'*64
        else:v['native_sha256']='0'*64
    elif change in('runtime','resource'):
        p=out/'execution.json';v=load(p);key='dense-blas/unexpected'if change=='runtime'else'static.npz';v['owned_before'][key]={'bytes':1,'sha256':'0'*64};v['owned_after']=v['owned_before']
    else:
        p=out/('inputs.json'if change=='request'else'stdout.json');v=load(p)
        if change in('request','result'):v['cases'].pop()
        else:
            c=next(c for c in v['cases']if c['kind']=='evidence'and c.get('result'))
            if change=='rows':c['result']['values'].pop()
            elif change=='names':c['result']['names'].reverse()
            else:c['encoder_calls'].reverse()
    p.write_text(json.dumps(v,ensure_ascii=True,allow_nan=False))
    if change not in('source','binary','runtime','resource'):
        e=load(out/'execution.json');e['request_sha256'if change=='request'else'stdout_sha256']=identity(p)['sha256'];(out/'execution.json').write_text(json.dumps(e))
    assert verify_capture(out,reference,sources)

def gate_sample(tmp_path):
    g=tmp_path/'gates';g.mkdir();names=['synthetic_'+str(i)for i in range(RUST_ROOTS)]
    (g/'rust-list.log').write_text('\n'.join(n+': test'for n in names));(g/'rust-tests.log').write_text('\n'.join('test '+n+' ... ok'for n in names)+f'\ntest result: ok. {RUST_ROOTS} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n')
    names=['synthetic_'+str(i)for i in range(PYTHON_ROOTS)];(g/'python-list.log').write_text('\n'.join('tests/rust_migration/test_numeric_evidence.py::'+n for n in names));xml=ET.Element('testsuite')
    for n in names:ET.SubElement(xml,'testcase',classname='tests.rust_migration.test_numeric_evidence',name=n)
    ET.ElementTree(xml).write(g/'python.xml');(g/'fmt.log').write_bytes(b'');(g/'clippy.log').write_text('Finished `dev` profile');return g
def test_complete_numeric_gate_helper_passes(tmp_path):assert not verify_gates(gate_sample(tmp_path))
@pytest.mark.parametrize('change',['omit','skip','rust','fmt','clippy','duplicate'])
def test_incomplete_numeric_gate_rejects(tmp_path,change):
    g=gate_sample(tmp_path)
    if change=='omit':p=g/'python-list.log';p.write_text('\n'.join(p.read_text().splitlines()[1:]))
    elif change=='skip':p=g/'python.xml';xml=ET.parse(p);ET.SubElement(next(xml.getroot().iter('testcase')),'skipped');xml.write(p)
    elif change=='rust':p=g/'rust-tests.log';p.write_text(p.read_text().replace('... ok','... FAILED',1))
    elif change=='fmt':(g/'fmt.log').write_text('format differs')
    elif change=='duplicate':p=g/'python-list.log';lines=p.read_text().splitlines();p.write_text('\n'.join([lines[0],*lines[:-1]]))
    else:(g/'clippy.log').write_text('error: failed')
    assert verify_gates(g)
