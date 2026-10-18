"""A real frozen encoder fixes the native model contract before the port."""
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest
from model2vec import StaticModel
from tokenizers import Tokenizer, models, pre_tokenizers

from tools.rust_migration.reference import freeze_reference
from tools.rust_migration.model_reference import capture, model_cases


@pytest.fixture
def frozen(tmp_path):
    source = tmp_path / 'source'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'src', source / 'src',
                    ignore=shutil.ignore_patterns('__pycache__'))
    return freeze_reference(source, tmp_path / 'oracle')


@pytest.fixture
def synthetic(tmp_path):
    snapshot = tmp_path / ('1' * 40)
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'alpha': 1, 'beta': 2}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    StaticModel(np.array([[0, 0, 0], [.1, .2, .3], [.4, .5, .6]], dtype=np.float16),
                tokenizer, normalize=True).save_pretrained(snapshot)
    artifacts = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in snapshot.iterdir() if p.name in ('config.json', 'tokenizer.json', 'model.safetensors')}
    registration = {'model_id': 'test/static', 'revision': snapshot.name,
                    'license': 'mit', 'artifacts': artifacts}
    return snapshot, registration


def test_capture_uses_frozen_model_and_rejects_drift(frozen, synthetic, tmp_path):
    # An import from the live checkout, unchecked data or a floating path must fail.
    snapshot, registration = synthetic
    result = capture(frozen, snapshot, tmp_path / 'result.json', registration=registration,
                     cases=[{'id': 'synthetic', 'calls': [
                         {'op': 'tokens', 'text': 'alpha mystery beta', 'max_length': None},
                         {'op': 'passages', 'texts': ['alpha beta', '']},
                     ]}])
    assert result['oracle']['frozen_import'] is True
    assert result['oracle']['runtime']['model2vec'] == '0.9.0'
    assert result['results'][0]['calls'][0] == [1, 2]
    vectors = result['results'][0]['calls'][1]
    assert vectors['rows'] == [0, 1]
    assert vectors['vectors'][1] == [0.0, 0.0, 0.0]
    # F16 means are exactly [.25, .35009765625, .4501953125], promoted by empty.
    assert vectors['vectors'][0] == pytest.approx([.40148318, .56223327, .72298342], abs=1e-7)
    changed = snapshot / 'config.json'
    before = changed.read_bytes()
    changed.write_bytes(before + b' ')
    with pytest.raises(ValueError, match='artifact'):
        capture(frozen, snapshot, tmp_path / 'bad.json', registration=registration)
    changed.write_bytes(before)
    other = snapshot.with_name('floating')
    snapshot.rename(other)
    with pytest.raises(ValueError, match='revision'):
        capture(frozen, other, tmp_path / 'bad.json', registration=registration)
    other.rename(snapshot)
    (frozen.root / 'src/ken/__init__.py').write_text('DRIFT = True\n')
    with pytest.raises(ValueError, match='reference'):
        capture(frozen, snapshot, tmp_path / 'bad.json', registration=registration)


def test_model_cases_pin_boundaries():
    # Removing adversarial lengths/Unicode/cache history must lose coverage.
    cases = {case['id']: case for case in model_cases()}
    assert {'empty', 'spaces', 'spanish', 'nfc', 'nfd', 'emoji', 'code', 'unknown',
            'pad', 'tokens-511', 'tokens-512', 'tokens-513', 'mixed-empty',
            'batch-1024', 'batch-1025', 'cache-history', 'unicode-prefix'} <= cases.keys()
    assert len(cases['batch-1025']['calls'][0]['texts']) == 1025
    assert len(cases['batch-1024']['calls'][0]['texts']) == 1024
    assert len(cases['cache-history']['calls']) >= 3
    assert cases['nfc']['calls'][0]['text'] == 'café'
    assert cases['nfd']['calls'][0]['text'] == 'cafe\u0301'
