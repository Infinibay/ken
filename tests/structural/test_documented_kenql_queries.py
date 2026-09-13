"""Run the KenQL guide, including its TOML dependency, against source witnesses."""
import re
import tomllib
from pathlib import Path

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from ken.structural.semantic import link_project


GUIDE = (Path(__file__).resolve().parents[2] / 'docs/structural-queries.md').read_text()
QUERIES = re.findall(r'```kenql\n(.*?)\n```', GUIDE, re.S)
LIBRARY = [SavedRule(**tomllib.loads(block))
           for block in re.findall(r'```toml\n(.*?)\n```', GUIDE, re.S)]
PYTHON = '''
class Base:
    def make(self): pass
class Product: pass
class Subject(Base):
    def make(self): return Product()
def consume(product): return product
def client(factory: Subject): consume(factory.make())
def public_transform():
    value = 1
    return value
public_transform()
'''
RUST = '#[derive(Clone)] struct Product { value: i32 }'
MUTATIONS = {
    'derives_clone': ('#[derive(Clone)]', '#[derive(Debug)]'),
    'product_flow': ('return Product()', 'return None'),
    'writes': ('    value = 1\n', ''),
    'returned_local': ('    value = 1\n', ''),
    'callers': ('public_transform', 'private_transform'),
}


@pytest.mark.parametrize('query', QUERIES,
                         ids=lambda q: re.search(r'query\s+(\w+)', q)[1])
@pytest.mark.parametrize('positive', [True, False], ids=['witness', 'missing-evidence'])
def test_kenql_guide_example(query, positive):
    name = re.search(r'query\s+(\w+)', query)[1]
    python, rust = PYTHON, RUST
    if not positive:
        before, after = MUTATIONS[name]
        assert before in python or before in rust
        python, rust = python.replace(before, after), rust.replace(before, after)
    units = [lower_source(python, 'python', 'guide.py'),
             lower_source(rust, 'rust', 'guide.rs')]
    assert all(not unit.diagnostics for unit in units)
    graph = link_project(units)
    registry = builtin_rules() + LIBRARY
    result = execute_rules(graph, [SavedRule('documented', query)], registry=registry)
    assert result['complete'], result
    assert bool(result['matches']) is positive, result
