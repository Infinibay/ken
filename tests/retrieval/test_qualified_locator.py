"""Named source locators must survive interpretation and stay model-free."""
from pathlib import Path
import pytest


@pytest.mark.parametrize('query', [
    'store.config::Reader.read_value',
    '`store.config::Reader.read_value`',
    'Locate the definition of `store.config::Reader.read_value`.',
    'Localiza la definición de `store.config::Reader.read_value`.',
    'Show the declaration of store.config::Reader.read_value.',
])
def test_locator_preserves_namespace_and_qualified_symbol(query):
    from ken.retrieval.source_locator import symbol_locator
    locator = symbol_locator(query)
    assert locator is not None
    assert locator.namespace == 'store.config'
    assert locator.qualname == 'Reader.read_value'


@pytest.mark.parametrize('query', [
    'Which function calls `store.config::Reader.read_value`?',
    'Locate a helper that calls store.config::Reader.read_value.',
    'Locate the definition of `store.config::Reader.read_value` and `other::read`.',
    'Localiza la función que usa `store.config::Reader.read_value`.',
    'Locate the definition of `../private::read`.',
    'Locate the definition of `store.config::Reader.read_value` that calls save.',
    'Locate the definition of `store.config::Reader` or another implementation.',
    'store.config::123value',
    'store.config::Reader..read_value',
])
def test_prose_references_and_multiple_targets_do_not_gain_locator_authority(query):
    from ken.retrieval.source_locator import symbol_locator
    assert symbol_locator(query) is None


@pytest.mark.parametrize('namespace,path', [
    ('store.config', 'src/store/config.py'),
    ('store.config', 'store/config/__init__.py'),
    ('lib/config/settings', 'lib/config/settings.ts'),
    ('lib/config/settings.ts', 'lib/config/settings.ts'),
    ('org.example', 'module/src/main/java/org/example/Reader.java'),
])
def test_locator_binds_both_module_or_path_and_full_symbol(namespace, path):
    from ken.retrieval.source_locator import symbol_locator
    from ken.retrieval.model import EntityKey
    locator = symbol_locator(namespace + '::Reader.read_value')
    assert locator is not None
    assert locator.matches(EntityKey(path, 'method', 'Reader.read_value', 'Reader', 0))
    assert not locator.matches(EntityKey('other/config.py', 'method', 'Reader.read_value', 'Reader', 0))
    assert not locator.matches(EntityKey(path, 'method', 'OtherReader.read_value', 'OtherReader', 0))
    assert not locator.matches(EntityKey(path, 'method', 'Reader.read_value_other', 'Reader', 0))


def test_exact_named_member_is_returned_without_loading_any_model(tmp_path, monkeypatch):
    from ken.db import connect, init_schema
    from ken.indexer import index_files
    from ken.retrieval.best_search import search_best
    from ken.retrieval.model import SearchRequest
    import ken.retrieval.best_search as best
    (tmp_path / 'src/store').mkdir(parents=True)
    source = '''class Reader:
    def read_value(self):
        return 7
class OtherReader:
    def read_value(self):
        return 8
'''
    (tmp_path / 'src/store/config.py').write_text(source)
    (tmp_path / 'other.py').write_text(source)
    def no_model():
        raise AssertionError('exact qualified source lookup must stay model-free')
    monkeypatch.setattr(best, 'default_resources', no_model)
    with connect(tmp_path / 'index.db') as conn:
        init_schema(conn)
        index_files(conn, tmp_path, [Path('src/store/config.py'), Path('other.py')])
        response = search_best(conn, tmp_path, SearchRequest(
            'Locate the definition of `store.config::Reader.read_value`.', piece_kind='symbol'))
    assert len(response.results) == 1
    assert response.results[0]['path'] == 'src/store/config.py'
    assert response.results[0]['entity']['qualname'] == 'Reader.read_value'


def test_locator_never_falls_back_to_same_symbol_in_another_module(tmp_path):
    from ken.db import connect, init_schema
    from ken.indexer import index_files
    from ken.retrieval.candidates import exact_candidates
    from ken.retrieval.model import SearchRequest
    (tmp_path / 'other.py').write_text('def read_value():\n    return 1\n')
    with connect(tmp_path / 'index.db') as conn:
        init_schema(conn)
        index_files(conn, tmp_path, [Path('other.py')])
        assert exact_candidates(conn, SearchRequest('missing::read_value')) == []
