"""An older admitted binary must be retired before search reads physical text."""
from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from ken.db import connect, init_schema
from ken.indexer import index_files
from ken.retrieval.model import EntityKey, Passage, Span
from ken.retrieval.storage import replace_file_passages


@pytest.fixture
def legacy_index(tmp_path):
    binary = b'\x95compressed\xff\n'
    (tmp_path / 'fuzz.input').write_bytes(binary)
    (tmp_path / 'code.py').write_text('def meaningful():\n    return 1\n')
    with connect(tmp_path / 'index.db') as conn:
        init_schema(conn)
        index_files(conn, tmp_path, [Path('code.py'), Path('fuzz.input')])
        from tests.retrieval.test_candidates import Encoder, profile
        from ken.retrieval.representations import index_embeddings
        index_embeddings(conn, profile(), encoders={'identity': Encoder(), 'behavior': Encoder()})
        file_id = conn.execute("SELECT id FROM ci_files WHERE path='fuzz.input'").fetchone()[0]
        # V7 admitted this replacement-decoded passage, authenticated to binary bytes.
        legacy = Passage(EntityKey('fuzz.input', 'module', None), Span(1, 1),
                         {'body': '\ufffdcompressed\ufffd', 'path': 'fuzz.input'},
                         hashlib.sha256(binary).hexdigest(), Span(1, 1))
        with conn:
            conn.execute('BEGIN')
            replace_file_passages(conn, file_id, [legacy])
            conn.execute('UPDATE ci_retrieval_files SET extractor_version=7')
        yield conn


def test_query_on_legacy_source_requests_preparation_before_decoding(legacy_index, tmp_path):
    from ken.retrieval.public import find_best
    result = find_best(legacy_index, tmp_path, 'meaningful')
    assert result.get('ok') is False
    assert result['code'] == 'search_preparation_required'
    assert 'ken retrieval prepare' in result['next_action']


def test_prepare_projection_rebuilds_legacy_source_even_with_current_profile(
        legacy_index, tmp_path, monkeypatch):
    import ken.retrieval.best_search as best
    from tests.retrieval.test_candidates import Encoder, profile
    from ken.retrieval.candidates import owner_passages
    from ken.retrieval.piece_catalog import SourceCatalog
    monkeypatch.setattr(best, 'potion_profile', profile)
    best._projection(legacy_index, tmp_path, SimpleNamespace(words=Encoder()))
    catalog = SourceCatalog(tmp_path, owner_passages(legacy_index))
    assert set(catalog.by_path) == {'code.py'}
    assert catalog.lines['code.py'] == ['def meaningful():', '    return 1']
    assert legacy_index.execute("SELECT COUNT(*) FROM ci_files WHERE path='fuzz.input'").fetchone()[0] == 1
