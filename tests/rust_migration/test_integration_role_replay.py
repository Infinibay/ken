"""Actual saved factory-role corruption is rejected independently of capture flags."""
import json,shutil
from pathlib import Path
import pytest
from tools.rust_migration.integration_replay import replay_role

REPO=Path(__file__).resolve().parents[2]
FIXTURE=REPO/'crates/ken-models/tests/fixtures/factory-integration/linux-potion'


def test_original_potion_identity_count_vectors_and_actual_concurrency_replay():
    assert replay_role(FIXTURE,REPO,'linux','potion','offline')==[]


@pytest.mark.parametrize('mutation',['family','spec','count','query','concurrent','preparation','key','network','runtime'])
def test_resealed_actual_role_bytes_cannot_hide_corruption(tmp_path,mutation):
    directory=tmp_path/'capture';shutil.copytree(FIXTURE,directory)
    path=directory/'stdout.json';actual=json.loads(path.read_bytes())
    if mutation=='family':actual['selection']['family']='static_table'
    elif mutation=='spec':actual['selection']['spec']['revision']='d'*64
    elif mutation=='count':actual['rows'][0]['result']['count']+=1
    elif mutation=='query':actual['rows'][1]['result']['vectors'][0][0]+=1.
    elif mutation=='concurrent':actual['rows'][2]['result']['vectors'].pop()
    elif mutation=='preparation':actual['rows'][1]['preparation']['assets_fingerprint']='e'*64
    elif mutation=='key':actual['compatible_key']='wrong-key'
    elif mutation=='network':
        with(directory/'exec.trace').open('a')as out:out.write('connect(3, {}, 16) = 0\n')
    elif mutation=='runtime':actual['runtime']['torch']={'backend':'torch'}
    path.write_text(json.dumps(actual))
    assert replay_role(directory,REPO,'linux','potion','offline'),mutation


def test_actual_anonymous_private_onnx_mapping_is_observed_not_its_original_filename():
    directory=FIXTURE.parent/'linux-context'
    assert replay_role(directory,REPO,'linux','context','offline')==[]


def test_deleting_actual_onnx_mapping_from_loader_output_rejects(tmp_path):
    directory=tmp_path/'context';shutil.copytree(FIXTURE.parent/'linux-context',directory)
    path=directory/'stderr.log';path.write_text('\n'.join(line for line in path.read_text().splitlines()if 'calling init:'not in line))
    assert replay_role(directory,REPO,'linux','context','offline')


@pytest.mark.parametrize('system', ['macos', 'linux'])
@pytest.mark.parametrize('phase', ['public', 'offline'])
@pytest.mark.parametrize('mutation', ['prepared', 'model', 'declared', 'verified', 'providers', 'runtime'])
def test_fastembed_actual_preparation_identity_is_required(tmp_path, system, phase, mutation):
    source = REPO / 'docs/validation/rust-migration-2026-10-21/m2-integration' / system / 'roles' / ('fastembed-' + phase)
    directory = tmp_path / 'capture'
    shutil.copytree(source, directory)
    assert replay_role(directory, REPO, system, 'fastembed', phase) == []
    path = directory / 'stdout.json'
    actual = json.loads(path.read_bytes())
    row = actual['rows'][0]
    trace = row['preparation']['trace']
    if mutation == 'prepared': row['prepared'] = False
    elif mutation == 'model': trace['model_fingerprint'] = 'f' * 64
    elif mutation == 'declared': trace['declared_artifacts_fingerprint'] = 'f' * 64
    elif mutation == 'verified': trace['verified_artifacts_fingerprint'] = 'f' * 64
    elif mutation == 'providers': trace['attempts'][0]['providers'] = ['CUDAExecutionProvider']
    elif mutation == 'runtime': trace['runtime']['sha256'] = 'f' * 64
    path.write_text(json.dumps(actual))
    assert replay_role(directory, REPO, system, 'fastembed', phase), mutation
