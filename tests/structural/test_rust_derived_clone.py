import pytest
from .test_gof_executable import evaluate

SOURCE = '''#[derive(Clone)]
struct Shape { size: i32 }
fn main() { let source = Shape { size: 2 }; let result = source.clone(); }
'''


@pytest.mark.parametrize('attribute', ['#[derive(Clone)]', '#[derive(Debug, Clone,)]', '#[derive(Clone)]\n// documentation\n#[allow(dead_code)]'])
def test_derived_clone_and_renaming(attribute):
    source = SOURCE.replace('#[derive(Clone)]', attribute)
    assert evaluate(source, 'rust', 'prototype')
    assert evaluate(source.replace('Shape', 'Item'), 'rust', 'prototype')


@pytest.mark.parametrize('old,new', [
 ('#[derive(Clone)]', '#[derive(Debug)]'),
 ('#[derive(Clone)]', '#[derive(custom::Clone)]'),
 ('source.clone()', 'source'),
 ('source.clone()', 'other.clone()'),
 ('#[derive(Clone)]', '#[cfg_attr(feature="copy", derive(Clone))]'),
])
def test_missing_derivation_or_wrong_receiver(old, new):
    assert not evaluate(SOURCE.replace(old, new), 'rust', 'prototype')


def test_inherent_clone_is_not_assumed_to_be_derived_clone():
    source = SOURCE + 'impl Shape { fn clone(&self) -> i32 { 0 } }'
    assert not evaluate(source, 'rust', 'prototype')
