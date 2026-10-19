"""Independent static-table capture must preserve its own lexical policy."""
import json
from pathlib import Path
import shutil

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from tools.rust_migration.reference import freeze_reference
from tools.rust_migration.table_reference import capture


def test_frozen_table_capture_preserves_unknown_and_empty(tmp_path):
    # Dropping UNK, borrowing the next row for empty text, or importing live
    # Python would violate observable results fixed independently here.
    source = tmp_path / 'source'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'src', source / 'src',
                    ignore=shutil.ignore_patterns('__pycache__'))
    reference = freeze_reference(source, tmp_path / 'oracle')
    tok = Tokenizer(models.WordLevel({'alfa': 0, 'beta': 1, 'gamma': 2,
                                      'delta': 3, '[UNK]': 4}, unk_token='[UNK]'))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    artifact = tmp_path / 'test.npz'
    np.savez_compressed(artifact, lut=np.arange(5, dtype=np.int32),
                        A=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1],
                                    [1, 1, 0], [0, 0, 2]], dtype=np.float32),
                        B=np.eye(3, dtype=np.float32),
                        tokenizer=np.frombuffer(tok.to_str().encode(), dtype=np.uint8),
                        meta=np.frombuffer(b'{"name":"test/table","dim":3}', dtype=np.uint8))
    cases = [{'id': 'policy', 'calls': [
        {'op': 'tokens', 'text': 'alfa mystery beta'},
        {'op': 'count', 'text': 'alfa mystery beta'},
        {'op': 'passages', 'texts': ['alfa beta', '', 'alfa']},
        {'op': 'queries', 'texts': []},
    ]}]
    result = capture(reference, artifact, tmp_path / 'result.json', cases=cases)
    assert result['oracle']['frozen_import'] is True
    assert result['dimension'] == 3
    calls = result['results'][0]['calls']
    assert calls[:2] == [[0, 4, 1], 3]
    assert calls[2][0] == pytest.approx([.70710677, .70710677, 0], abs=1e-7)
    assert calls[2][1:] == [[0, 0, 0], [1, 0, 0]]
    assert calls[3] == []
    assert result['results'][0]['peak_after_load_bytes'] > 0
    expected = json.loads((tmp_path / 'result.json').read_text())
    with pytest.raises(ValueError, match='artifact'):
        capture(reference, artifact, tmp_path / 'bad.json', cases=cases,
                expected_sha256='0' * 64)
    assert expected['artifact']['sha256'] == result['artifact']['sha256']
    (reference.root / 'src/ken/embedder/static_head.py').write_text('DRIFT=True\n')
    with pytest.raises(ValueError, match='reference'):
        capture(reference, artifact, tmp_path / 'bad.json', cases=cases)
