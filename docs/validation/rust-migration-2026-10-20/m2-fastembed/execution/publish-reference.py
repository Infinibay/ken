from pathlib import Path
import gzip,hashlib,json,shutil
from tools.rust_migration.fastembed_reference import read_chunk,validate_model_record,fastembed_cases
root=Path.cwd();private=root/'.ken/rust-migration/m2-fastembed'
registry=private/'registry-draft.json';catalog=json.loads(registry.read_bytes());cases=fastembed_cases([m['name'] for m in catalog['models']])
public=root/'docs/validation/rust-migration-2026-10-20/m2-fastembed'
stage=private/'public-t1-stage';stage.mkdir(exist_ok=False)
platforms=[]
def digest(raw):return hashlib.sha256(raw).hexdigest()
for system,directory in [('Darwin','reference-macos-attempt3'),('Linux','reference-linux-attempt1')]:
    source=private/directory;index=json.loads((source/'index.json').read_bytes())
    assert index['platform']==system and index['architecture'] in {'arm64','aarch64'}
    assert index['cases']==300 and len(index['models'])==30 and len(index['tokenizers']['repositories'])==29
    assert index['registry_sha256']==digest(registry.read_bytes())
    assert json.loads((source/'cases.json').read_bytes())==cases
    actual=[]
    for model,definition in zip(index['models'],catalog['models'],strict=True):
        assert model['model']==definition['name']
        record=read_chunk(source,model['record']);validate_model_record(record,definition,[c for c in cases if c['model']==model['model']])
        actual.append(record)
    for row in index['tokenizers']['repositories']:read_chunk(source,row['record'])
    target=stage/('reference-macos' if system=='Darwin' else 'reference-linux');target.mkdir()
    files=[]
    for path in sorted(source.iterdir()):
        assert path.is_file() and not path.is_symlink()
        raw=path.read_bytes();compressed=path.suffix=='.log'
        name=path.name+('.gz' if compressed else '')
        payload=gzip.compress(raw,mtime=0) if compressed else raw
        (target/name).write_bytes(payload)
        row={'path':name,'bytes':len(payload),'sha256':digest(payload)}
        if compressed:row.update(original_path=path.name,raw_bytes=len(raw),raw_sha256=digest(raw),compression='gzip')
        files.append(row)
    inventory={'format':'ken-fastembed-reference-files/1','files':files}
    (target/'files.json').write_text(json.dumps(inventory,indent=2)+'\n')
    platforms.append({'platform':system,'architecture':index['architecture'],'directory':target.name,
                      'index_sha256':digest((target/'index.json').read_bytes()),'files_sha256':digest((target/'files.json').read_bytes()),
                      'models':len(actual),'cases':sum(len(r['results']) for r in actual),
                      'failed_cases':sum('error' in c for r in actual for c in r['results']),
                      'vector_rows':sum(c['shape'][0] for r in actual for c in r['results'] if 'shape' in c),
                      'tokenizers':len(index['tokenizers']['repositories'])})
mac_index=json.loads((stage/'reference-macos/index.json').read_bytes())
linux_index=json.loads((stage/'reference-linux/index.json').read_bytes())
for key in ['provenance','tooling','registry_sha256','cases_sha256']:
    assert mac_index[key]==linux_index[key],key
assert mac_index['tooling']=={name:digest((root/'tools/rust_migration'/name).read_bytes()) for name in mac_index['tooling']}
assert platforms[0]['cases']==platforms[1]['cases']==300
assert platforms[0]['failed_cases']==platforms[1]['failed_cases']==8
assert platforms[0]['vector_rows']==platforms[1]['vector_rows']==15660
assert json.loads((stage/'reference-macos/cases.json').read_bytes())==json.loads((stage/'reference-linux/cases.json').read_bytes())
(stage/'cases.json').write_bytes((stage/'reference-macos/cases.json').read_bytes())
snapshot_audit=json.loads((private/'reference-snapshot-audit.json').read_bytes())
assert snapshot_audit['macos']['fingerprint']==mac_index['reference_fingerprint']
assert snapshot_audit['linux']['fingerprint']==linux_index['reference_fingerprint']
shutil.copy2(private/'reference-snapshot-audit.json',stage/'reference-snapshot-audit.json')
result={'original_source_sha256':snapshot_audit['source_sha256'],'original_source_files':snapshot_audit['source_files'],'format':'ken-fastembed-reference-index/1','registry_sha256':digest(registry.read_bytes()),
        'cases_sha256':digest((stage/'cases.json').read_bytes()),'platforms':platforms,
        'native_acceptance':False,'M2_accepted':False,
        'timing_scope':'record.process_wall_ns is the controller capture span including sandbox, child, output validation and post-execution artifact hashing; per-case elapsed_ns surrounds original embed call'}
(stage/'reference-index.json').write_text(json.dumps(result,indent=2)+'\n')
observations=stage/'baseline-fp16';observations.mkdir()
for name in ['fp16-uninstrumented.py','fp16-uninstrumented-macos.json','fp16-uninstrumented-macos.stderr.log','fp16-uninstrumented-linux.json','fp16-uninstrumented-linux.stderr.log','fp16-linux-graph-verification.log']:
    shutil.copy2(private/name,observations/name)
auxiliary=stage/'auxiliary';auxiliary.mkdir()
shutil.copy2(private/'case-alias-original-preflight.json',auxiliary/'case-alias-original-preflight.json')
shutil.copy2(root/'.superpowers/sdd/2026-10-20-rust-m2-fastembed/observe-case-alias.py',auxiliary/'observe-case-alias.py')
resource=root/'crates/ken-models/resources/fastembed-catalog.json';assert not resource.exists()
resource.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(registry,resource)
assert not public.exists();public.parent.mkdir(parents=True,exist_ok=True);stage.rename(public)
print(json.dumps(result,indent=2))
