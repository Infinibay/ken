"""Re-sealing altered compressed receipts cannot make missing evidence pass."""
import json,shutil,tarfile
from pathlib import Path
import pytest
from tools.rust_migration.import_evidence import aggregate_import_matrix
from tools.rust_migration.native_json import identity
REPO=Path(__file__).resolve().parents[2]
PROOF=REPO/'docs/validation/rust-migration-2026-10-23/m3-imports-review'
def seal(folder):
    rows=[dict(path=str(p.relative_to(folder)),**identity(p))for p in sorted(folder.iterdir())if p.is_file()and p.name!='FILES.json']
    (folder/'FILES.json').write_text(json.dumps(dict(files=rows),indent=2)+'\n')
def replay(proof,tmp_path,current=False):
    source=tmp_path/'source';source.mkdir()
    with tarfile.open(proof/'sources.tar.gz')as archive:archive.extractall(source,filter='data')
    return aggregate_import_matrix(proof,REPO,snapshot=source,current=current)
def test_actual_matrix_accepts_only_import_resolution(tmp_path):
    result=replay(PROOF,tmp_path,current=True);assert result['passed'],result
    assert result['M3c_accepted']and not result['M3_accepted']and not result['migration_complete']

@pytest.mark.parametrize('mutation',['platform','source','request','resource','stdout','original','gate'])
def test_resealed_compressed_evidence_rejects_tampering(tmp_path,mutation):
    out=tmp_path/'proof';shutil.copytree(PROOF,out);index=json.loads((out/'INDEX.json').read_bytes())
    if mutation=='platform':index['platforms'].pop('linux')
    elif mutation=='source':index['sources']['Cargo.lock']['sha256']='0'*64
    else:
        capture=tmp_path/'capture';capture.mkdir()
        with tarfile.open(out/'linux-capture.tar.gz')as archive:archive.extractall(capture,filter='data')
        if mutation=='gate':(capture/'gates/rust-tests.log').write_text('test result: ok. 45 passed; 0 failed; 0 ignored;\n')
        elif mutation=='original':
            path=capture/'original/original-observations.json';value=json.loads(path.read_bytes());value['cases'].pop();path.write_text(json.dumps(value))
        elif mutation=='resource':
            path=capture/'native/BUILD.json';value=json.loads(path.read_bytes());value['resources'][0]['sha256']='0'*64;path.write_text(json.dumps(value))
        else:
            path=capture/'native'/('inputs.json'if mutation=='request'else'stdout.json');value=json.loads(path.read_bytes())
            if mutation=='request':value['cases'][0]['expected']={}
            else:value['cases'].pop()
            path.write_text(json.dumps(value));receipt=capture/'native/execution.json';execution=json.loads(receipt.read_bytes());execution['request_sha256'if mutation=='request'else'stdout_sha256']=identity(path)['sha256'];receipt.write_text(json.dumps(execution))
        with tarfile.open(out/'linux-capture.tar.gz','w:gz')as archive:
            for path in capture.iterdir():archive.add(path,arcname=path.name)
    (out/'INDEX.json').write_text(json.dumps(index));seal(out)
    assert not replay(out,tmp_path)['passed']
