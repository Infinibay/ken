"""Authentication owns bytes once; fresh hashes cannot legitimize false results."""
from copy import deepcopy
import gzip
import hashlib
import json
import shutil

import pytest
from test_fastembed_validate import fastembed_row, PUBLIC
from test_storage_validate import execution_fixture as storage_fixture
from tools.rust_migration.fastembed_reference import write_chunk
from tools.rust_migration.fastembed_evidence import authenticate_chunk, execution_errors, seal_execution


def sha(data):return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize('damage',['compressed-hash','compressed-size','raw-hash','raw-size',
    'bomb','trailing','truncated','duplicate-json'])
def test_chunk_rejects_malformed_or_unbounded_payload(tmp_path,damage):
    receipt=write_chunk(tmp_path,'raw',{'value':1});payload=(tmp_path/receipt['path']).read_bytes()
    assert authenticate_chunk(payload,receipt)=={'value':1}
    if damage=='compressed-hash':receipt['sha256']='0'*64
    elif damage=='compressed-size':receipt['bytes']+=1
    elif damage=='raw-hash':receipt['raw_sha256']='0'*64
    elif damage=='raw-size':receipt['raw_bytes']+=1
    else:
        if damage=='bomb':payload=gzip.compress(b'x'*(16*1024*1024+1),mtime=0)
        elif damage=='trailing':payload+=b'garbage'
        elif damage=='truncated':payload=payload[:-1]
        else:
            raw=b'{"value":1,"value":2}';payload=gzip.compress(raw,mtime=0)
            receipt.update(raw_bytes=len(raw),raw_sha256=sha(raw))
        receipt.update(bytes=len(payload),sha256=sha(payload))
    with pytest.raises(ValueError):authenticate_chunk(payload,receipt)


def execution_fixture(root,row,folder='linux'):
    storage_fixture(root/'base',row['storage_base'])
    row['gates'].update(deepcopy(row['storage_base']['gates']))
    for key,source in [('fastembed_parity',f'native-{folder}-attempt1'),
                       ('fastembed_ownership',f'ownership-{folder}-attempt1')]:
        folder=key.replace('_','-');shutil.copytree(PUBLIC/source,root/folder)
        (root/folder/'summary.json').write_text(json.dumps(row[key]))
    row['execution_artifacts']=seal_execution(root)


@pytest.mark.parametrize('damage',['missing','altered','unlisted','false-vector','false-ownership',
    'source','source-identity','process','request','stderr','trace','false-base'])
def test_authenticated_raw_proof_rejects_resealed_false_semantics(tmp_path,damage):
    row=fastembed_row();execution_fixture(tmp_path,row)
    assert execution_errors(tmp_path,row)==[]
    key='fastembed_ownership' if damage=='false-ownership' else 'fastembed_parity'
    item=row[key]['models'][0];folder=tmp_path/key.replace('_','-')/item['directory']
    path=folder/item['record']['path']
    if damage=='missing':path.unlink()
    elif damage=='altered':path.write_bytes(path.read_bytes()+b'x')
    elif damage=='unlisted':
        manifest=tmp_path/'execution-artifacts.json';data=json.loads(manifest.read_bytes())
        name=path.relative_to(tmp_path).as_posix()
        data['files']=[r for r in data['files'] if r['path']!=name]
        manifest.write_text(json.dumps(data));row['execution_artifacts']['sha256']=sha(manifest.read_bytes())
    elif damage=='false-base':
        path=tmp_path/'base/storage-parity/native.stdout.json'
        data=json.loads(path.read_bytes());data['results'][2]['output']['values'][0]='wrong'
        path.write_text(json.dumps(data))
        from tools.rust_migration.storage_evidence import seal_execution as storage_seal
        row['storage_base']['execution_artifacts']=storage_seal(tmp_path/'base')
        (tmp_path/'base/summary.json').write_text(json.dumps(row['storage_base']))
        row['execution_artifacts']=seal_execution(tmp_path)
    else:
        record=authenticate_chunk(path.read_bytes(),item['record'])
        if damage=='false-ownership':record['facts']['source_removed']=False
        elif damage=='false-vector':
            frames=[json.loads(line) for line in record['stdout'].splitlines()]
            frames[2]['result']['vectors_f32le_hex']='00000000'*768
            record['stdout']=''.join(json.dumps(frame)+'\n' for frame in frames)
        elif damage=='source':record['source_after']['artifacts']['config.json']['sha256']='0'*64
        elif damage=='source-identity':
            record['source_before']['snapshot']='/tmp/unrelated-revision'
            record['source_after']['snapshot']='/tmp/unrelated-revision'
        elif damage=='process':record['process']['native_exit']=False
        elif damage=='request':record['requests'][1]['input']='oracle'
        elif damage=='stderr':record['stderr']='fabricated warning'
        elif damage=='trace':
            trace=folder/'native-exec.trace';trace.write_text(trace.read_text()+'1 execve("python", [], 0x0) = 0\n')
        item['record']=write_chunk(folder,'ownership' if key.endswith('ownership') else 'native',record)
        (folder.parent/'summary.json').write_text(json.dumps(row[key]))
        row['execution_artifacts']=seal_execution(tmp_path)
    assert execution_errors(tmp_path,row),damage


@pytest.mark.parametrize('folder',['linux','macos'])
def test_execution_authenticates_each_file_once_and_reuses_owned_bytes(tmp_path,monkeypatch,folder):
    from tools.rust_migration import policy_evidence as policy
    row=fastembed_row(folder);execution_fixture(tmp_path,row,folder)
    reads={};read=policy._read
    def once(root,name):
        reads[name]=reads.get(name,0)+1;assert reads[name]==1,name
        return read(root,name)
    monkeypatch.setattr(policy,'_read',once)
    assert execution_errors(tmp_path,row)==[]
