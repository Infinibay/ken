from pathlib import Path
import copy,gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_python_original_corpus_is_complete_and_validated():
    from tools.rust_migration.python_witnesses_reference import FIXTURE,cases,validate_reference
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    assert len(cases())>=100 and not validate_reference(value)
    assert len({c['id']for c in cases()})==len(cases())

def test_existing_original_destination_rejects_before_loading_any_source(tmp_path):
    from tools.rust_migration.python_witnesses_reference import capture
    with pytest.raises(FileExistsError):capture(None,tmp_path)

@pytest.mark.parametrize('change',['source','source-code','observer','inputs','input-answer','result','owners','runtime'])
def test_changed_or_resealed_original_contract_rejects(change):
    from tools.rust_migration.python_witnesses_reference import FIXTURE,validate_reference,digest
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    if change=='source':value['reference_fingerprint']='0'*64
    elif change=='source-code':value['original_source_sha256']='0'*64
    elif change=='observer':value['script_sha256']='0'*64
    elif change=='inputs':value['cases'][0]['input']['files']={}
    elif change=='input-answer':value['cases'][0]['input']['expected']={}
    elif change=='result':value['cases'][0]['result'][0]['warm']=['invented']
    elif change=='owners':value['cases'][0]['input']['owners']=[]
    else:value['runtime']['python']='3.14.0'
    value['observations_sha256']=digest(value)
    assert validate_reference(value)

def test_compatibility_corpus_is_independent_and_validated():
    from tools.rust_migration.python_witnesses_reference import validate_reference,cases
    from tools.rust_migration.python_witnesses_compat import FIXTURE_COMPAT,compatibility_cases
    value=json.loads(gzip.decompress((ROOT/FIXTURE_COMPAT).read_bytes()))
    assert len(compatibility_cases())>=30 and not validate_reference(value)
    assert not ({c['id']for c in cases()} & {c['id']for c in compatibility_cases()})
    from tools.rust_migration.python_witnesses_review import FIXTURE_REVIEW,review_cases
    review=json.loads(gzip.decompress((ROOT/FIXTURE_REVIEW).read_bytes()))
    assert len(review_cases())>=30 and not validate_reference(review)
    assert not ({c['id']for c in review_cases()} & {c['id']for c in cases()+compatibility_cases()})

def test_vendored_parser_runtime_sources_and_license_match_upstream():
    import hashlib
    root=ROOT/'crates/ken-retrieval/vendor/ruff-python-parser'
    record=json.loads((root/'UPSTREAM.json').read_bytes())
    assert record['archive_sha256']=='01e6ee78bd9671fb5766664b2695fe1f2a92a961f4d9101646c570d8acdb1e0b'
    patches=json.loads((root/'PATCHES.json').read_bytes())
    assert {row['path']for row in patches}=={'src/lexer.rs','src/lexer/indentation.rs'}
    patched={row['path']:row for row in patches}
    expected={name:row for name,row in record['source_files'].items()if name!='Cargo.toml'}
    for name,row in expected.items():
        raw=(root/name).read_bytes()
        if name in patched:
            patch=patched[name];assert hashlib.sha256(raw).hexdigest()==patch['local_sha256']
            assert raw.count(patch['after'].encode())==1
            raw=raw.replace(patch['after'].encode(),patch['before'].encode(),1)
        assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
    assert {p.relative_to(root).as_posix()for p in root.rglob('*.rs')}=={n for n in expected if n.endswith('.rs')}
    assert hashlib.sha256((root/'LICENSE').read_bytes()).hexdigest()==record['additional_license']['sha256']
    import tomllib
    manifest=tomllib.loads((root/'Cargo.toml').read_text())
    assert manifest['dependencies']['unicode_names2']['version']=='=1.2.0'
    assert manifest['dependencies']['unicode-normalization']['version']=='=0.1.22'
    assert not manifest.get('dev-dependencies') and not manifest.get('test')
