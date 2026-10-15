import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def assets(tmp_path):
    from ken.retrieval.query_expansion import REQUIRED_ARTIFACTS
    artifacts = {}
    for name in REQUIRED_ARTIFACTS:
        path = tmp_path/name
        path.write_bytes(name.encode())
        artifacts[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
    return {'model_id': 'test/translator', 'revision': 'a'*40, 'artifacts': artifacts}


def test_english_requests_do_not_load_models_or_read_weights(tmp_path):
    from ken.retrieval.query_expansion import LocalQueryExpansion
    registration = assets(tmp_path)
    for path in tmp_path.iterdir():
        path.unlink()
    expand = LocalQueryExpansion(tmp_path, registration,
        load_runtime=lambda path: (_ for _ in ()).throw(AssertionError('must stay lazy')))
    assert expand('Where are names normalized?') == 'Where are names normalized?'
    assert len(expand.revision) == 64


def test_spanish_expansion_restores_protected_code_identifiers_and_loads_once(tmp_path):
    from ken.retrieval.query_expansion import LocalQueryExpansion
    loaded = []
    class Pieces:
        def encode(self, text, out_type=str):
            return text.split()
        def decode(self, tokens):
            return ' '.join(tokens)
    class Translator:
        def translate_batch(self, rows, **kwargs):
            return [SimpleNamespace(hypotheses=[['Find', 'Z', 'X', 'Q', '0', 'Q', 'X', 'Z',
                'and', 'ZXQ1QXZ.']])]
    def load(path):
        loaded.append(path)
        return Translator(), Pieces(), Pieces()
    expand = LocalQueryExpansion(tmp_path, assets(tmp_path), load_runtime=load)
    query = '¿Dónde se invoca `Client.send` con project_name?'
    assert expand(query) == 'Find `Client.send` and project_name.'
    assert expand(query) == 'Find `Client.send` and project_name.'
    assert loaded == [tmp_path]


def test_modified_translation_artifact_is_rejected_before_inference(tmp_path):
    from ken.retrieval.query_expansion import LocalQueryExpansion
    registration = assets(tmp_path)
    (tmp_path/'model.bin').write_bytes(b'changed')
    expand = LocalQueryExpansion(tmp_path, registration,
        load_runtime=lambda path: (_ for _ in ()).throw(AssertionError('unverified model')))
    with pytest.raises(ValueError, match='artifact'):
        expand('¿Dónde se normalizan los nombres?')
