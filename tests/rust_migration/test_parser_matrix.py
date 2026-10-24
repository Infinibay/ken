"""Resealed receipts still require complete original/native platform evidence."""
import json
import os
from pathlib import Path
import shutil
import tarfile
import pytest
from tools.rust_migration.parser_evidence import aggregate_parser_matrix
from tools.rust_migration.parser_validate import identity

REPO = Path(__file__).resolve().parents[2]
PROOF = REPO / 'docs/validation/rust-migration-2026-10-23/m3-parsers-review'

def seal(folder):
    rows = [dict(path=str(p.relative_to(folder)), **identity(p)) for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'FILES.json']
    (folder / 'FILES.json').write_text(json.dumps(dict(files=rows), indent=2) + '\n')

@pytest.fixture(scope='module')
def historical_repo(tmp_path_factory):
    # Replaying a historical certificate requires its exact native sources and
    # preserved originals, not today's Rust tree or modified Python checkout.
    repo=tmp_path_factory.mktemp('archived-parser-repo')
    shutil.copytree(PROOF/'native-sources',repo,dirs_exist_ok=True)
    original=Path(os.environ.get('KEN_RUST_REFERENCE',REPO/'.ken/rust-migration/portable-reference'))
    baseline=REPO/'docs/validation/rust-migration-2026-10-18/baseline.json'
    for row in json.loads(baseline.read_bytes())['files']:
        target=repo/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original/row['path'],target)
    target=repo/'docs/validation/rust-migration-2026-10-18/baseline.json'
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(baseline,target)
    predecessor=json.loads((PROOF/'INDEX.json').read_bytes())['predecessor']['path']
    shutil.copytree(REPO/predecessor,repo/predecessor)
    return repo

def test_actual_matrix_accepts_only_archived_parsers(historical_repo):
    result = aggregate_parser_matrix(PROOF, historical_repo, current=True)
    assert result['passed'], result
    assert result['M3b_accepted'] and not result['M3_accepted'] and not result['migration_complete']

def test_archived_acceptance_cannot_certify_changed_current_sources(historical_repo,tmp_path):
    repo=tmp_path/'changed';shutil.copytree(historical_repo,repo)
    source=repo/'crates/ken-syntax/src/grammar.rs'
    source.write_bytes(source.read_bytes()+b'\n// changed after archived acceptance\n')
    result=aggregate_parser_matrix(PROOF,repo,current=True)
    assert not result['passed']and 'current parser source differs'in result['errors']

@pytest.mark.parametrize('mutation', ['platform', 'source', 'grammar', 'original', 'missing', 'gate', 'summary'])
def test_resealed_matrix_cannot_hide_missing_or_changed_proof(tmp_path, mutation, historical_repo):
    out = tmp_path / 'proof'; shutil.copytree(PROOF, out)
    index = json.loads((out / 'INDEX.json').read_bytes())
    if mutation == 'platform': index['platforms'].pop('linux')
    elif mutation == 'source': index['sources']['Cargo.lock']['sha256'] = '0' * 64
    elif mutation == 'missing': (out / 'gates/linux/python.xml').unlink()
    elif mutation == 'gate': (out / 'gates/linux/rust-tests.log').write_text('test result: ok. 31 passed; 0 failed; 0 ignored;\n')
    elif mutation == 'summary':
        index['passed'] = True
        (out / 'gates/macos/python.xml').write_text('<testsuite tests="36" failures="0"/>')
    else:
        capture = tmp_path / 'capture'; capture.mkdir()
        with tarfile.open(out / 'linux-capture.tar.gz') as archive: archive.extractall(capture, filter='data')
        if mutation == 'grammar':
            for name in ('execution', 'BUILD'):
                path = capture / 'native' / (name + '.json'); value = json.loads(path.read_bytes()); value['resources'][0]['sha256'] = '0' * 64
                if name == 'execution': value['manifest']['libraries'] = value['resources']
                path.write_text(json.dumps(value))
        else:
            path = capture / 'original/original-observations.json'; value = json.loads(path.read_bytes()); value['cases'].pop(); path.write_text(json.dumps(value))
        with tarfile.open(out / 'linux-capture.tar.gz', 'w:gz') as archive:
            for name in ('native', 'original'): archive.add(capture / name, arcname=name)
    (out / 'INDEX.json').write_text(json.dumps(index)); seal(out)
    assert not aggregate_parser_matrix(out, historical_repo)['passed']
