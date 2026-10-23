"""Tampering with actual saved native observations cannot be fixed by resealing hashes."""
import json
from pathlib import Path
import shutil
import pytest
from tools.rust_migration.integration_replay import replay_transformer_profile

FIXTURE=Path(__file__).resolve().parents[2]/'crates/ken-models/tests/fixtures/factory-integration/linux-bge-cpu-bfloat16'
REPO=Path(__file__).resolve().parents[2]


def test_actual_saved_linux_factory_replays_against_pinned_direct_and_original_identity():
    assert replay_transformer_profile(FIXTURE,REPO,'linux',0)==[]


@pytest.mark.parametrize('mutation',['role','family','revision','runtime','module','compatible-key','legacy-version','source-path','offline-connect','trace-exec','partial-output','values','loaded-cold'])
def test_changed_raw_factory_fails_even_with_recomputed_transport_hashes(tmp_path,mutation):
    directory=tmp_path/'capture';shutil.copytree(FIXTURE,directory)
    path=directory/'stdout.json';actual=json.loads(path.read_bytes())
    if mutation in('role','family'):actual['selection'].pop(mutation)
    elif mutation=='revision':actual['selection']['spec']['revision']='e'*40
    elif mutation=='runtime':actual['rows'][0]['preparation']['trace']['runtime']['declared_core_version']='2.8.0'
    elif mutation=='module':actual['rows'][0]['preparation']['trace']['runtime']['module']['sha256']='f'*64
    elif mutation=='compatible-key':actual['compatible_key']='wrong-key'
    elif mutation in('legacy-version','source-path'):
        p=directory/'inputs.json';request=json.loads(p.read_bytes())
        if mutation=='legacy-version':request['selection']['legacy']['backends']['sentence-transformers'][1][1]='2.8.0'
        else:request['source_overrides']['BAAI/bge-m3']='/tmp/'+'f'*40
        p.write_text(json.dumps(request))
    elif mutation=='offline-connect':
        with (directory/'exec.trace').open('a')as out:out.write('connect(3, {}, 16) = 0\n')
    elif mutation=='trace-exec':
        with (directory/'exec.trace').open('a')as out:out.write('execveat(3, "python", [], [], 0) = 0\n')
    elif mutation=='partial-output':actual['rows'][0]['result']['vectors'].pop()
    elif mutation=='values':actual['rows'][0]['result']['vectors'][0][0]+=1
    elif mutation=='loaded-cold':actual['initial_prepared']=True
    path.write_text(json.dumps(actual))
    assert replay_transformer_profile(directory,REPO,'linux',0),mutation
