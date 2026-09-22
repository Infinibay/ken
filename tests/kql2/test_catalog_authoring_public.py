"""Completed source-authoring files cannot silently reintroduce graph syntax."""
from pathlib import Path
import re
import tomllib
import pytest
from ken.structural.catalog import catalog, _load_catalog

ROOT=Path(__file__).resolve().parents[2]/'src/ken/structural'

@pytest.mark.parametrize('path',[
 'patterns/abstract-factory.toml','patterns/facade.toml',
 'patterns/factory-method.toml','patterns/template-method.toml',
 'patterns/decorator.toml','modern_patterns/dependency-injection.toml',
 'modern_patterns/continuation-wrapper.toml',
 'modern_patterns/adapted-continuation-wrapper.toml',
])
def test_completed_source_files_do_not_contain_an_internal_query(path):
    data=tomllib.loads((ROOT/path).read_text())
    assert not data.get('legacy_query')
    for entry in [data,*data.get('variants',[]),*data.get('operations',[])]:
        assert entry.get('query'),entry.get('id')
        assert not re.search(r'\b(?:edge|walk)\s+\w+',entry['query']),entry.get('id')
        assert 'GraphTerm' not in entry['query'],entry.get('id')


def test_catalog_only_advertises_existing_legacy_definitions():
    rules={rule.id:rule for rule in _load_catalog()}
    for item in catalog():
        assert ('legacy_id' in item) == bool(rules[item['id']].legacy_query)
