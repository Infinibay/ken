"""Original decisions are captured before any native policy implementation."""
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil

import pytest

from tools.rust_migration.reference import freeze_reference

ROOT=Path(__file__).resolve().parents[2]
LEGACY='sentence-transformers/all-MiniLM-L6-v2'
POTION='minishlab/potion-code-16M-v2'


@pytest.fixture(scope='module')
def original(tmp_path_factory):
    root=tmp_path_factory.mktemp('model-policy-original')
    source=root/'source'
    shutil.copytree(ROOT/'src',source/'src',ignore=shutil.ignore_patterns('__pycache__'))
    return freeze_reference(source,root/'frozen')


def test_cases_cover_source_storage_and_override_boundaries():
    from tools.rust_migration.policy_reference import policy_cases,policy_prompts
    cases=policy_cases()
    assert len(cases)==1292
    assert len({c['id'] for c in cases})==1292
    assert len([c for c in cases if c['id'].startswith('cartesian-')])==1280
    special={c['id']:c for c in cases if not c['id'].startswith('cartesian-')}
    assert special['sidecar-zero']['source_setup']['vec_slot']==0
    assert special['sidecar-negative']['source_setup']['vec_slot']==-1
    assert special['empty-inline']['source_setup']['embedding_hex']==''
    for name in ['sidecar-zero','sidecar-negative','empty-inline']:
        assert special[name]['input']['facts']['file_vectors_present'] is True
    for case in cases:
        assert case['input']['forced_variants']==[None,'','forced/model',' ','\x1c','\0']
    assert 'Qwen/Qwen3-EmbeddingX' in policy_prompts()
    assert 'qwen/Qwen3-Embedding-0.6B' in policy_prompts()


def test_capture_uses_real_frozen_policy_without_loading_an_encoder(original,tmp_path):
    from tools.rust_migration.policy_reference import capture_policy
    row=capture_policy(original,tmp_path/'oracle.json')
    assert row['scope']=='original-model-policy/1'
    assert row['oracle']['frozen_import'] is True
    assert row['oracle']['unicode']=='15.0.0'
    assert row['oracle']['sources']['src/ken/embedder/__init__.py']==hashlib.sha256(
        (original.root/'src/ken/embedder/__init__.py').read_bytes()).hexdigest()
    assert len(row['results'])==len(row['observations'])==1292
    assert all(r['selection_preserves_rows'] for r in row['observations'])
    assert all(r['encoder_singleton_unloaded'] for r in row['observations'])
    prompts={r['model']:r for r in row['prompts']}
    assert prompts['intfloat/e5-base']['query']=='query: '
    assert prompts['intfloat/e5-base']['passage']=='passage: '
    assert prompts['Qwen/Qwen3-EmbeddingX']['query']==(
        "Instruct: Given a developer's question, retrieve the code file that answers it\nQuery: ")
    assert prompts['qwen/Qwen3-Embedding-0.6B']['asymmetric'] is False


def test_missing_empty_and_existing_vector_markers_preserve_original_pin_decisions(original,tmp_path):
    from tools.rust_migration.policy_reference import capture_policy
    row=capture_policy(original,tmp_path/'oracle.json')
    results={r['id']:r for r in row['results']}
    observations={r['id']:r for r in row['observations']}
    for name in ['sidecar-zero','sidecar-negative','empty-inline']:
        assert results[name]['project']=={'model':LEGACY,'initial_pin':None}
    null=results['null-meta']
    assert null['project']=={'model':POTION,'initial_pin':{'model':POTION,'document_space':2}}
    assert observations['null-meta']['metadata_before']['embed_doc_space']=='9'
    assert observations['null-meta']['metadata_after']['embed_doc_space']=='2'
    assert observations['null-meta']['metadata_after']['unrelated']=='keep'
    assert results['stored-nul']['project']=={'model':'\0','initial_pin':None}
    assert results['env-control']['project']['model']=='\x1c'
    empty=results['cartesian-0-0-1-0-1']
    assert empty['project']=={'model':POTION,'initial_pin':None}
    assert empty['active'][-2:]==['\x1c','\0']


def test_capture_rejects_incomplete_reference_before_output(original,tmp_path):
    from tools.rust_migration.policy_reference import capture_policy
    empty=tmp_path/'missing-source';empty.mkdir()
    output=tmp_path/'oracle.json'
    with pytest.raises(ValueError,match='frozen source drift'):
        capture_policy(replace(original,root=empty),output)
    assert not output.exists()
