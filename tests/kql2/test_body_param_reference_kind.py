"""``reference_kind`` as a matchable parameter property.

The C++ copy constructor differs from the move and by-value spellings only in
the declarator of its single parameter (IR 1.60 records ``lvalue`` for
``const X&`` and ``rvalue`` for ``X&&``), so ``prototype#language-copy`` needs
to state that spelling as a clause property.
"""
import pathlib
import tempfile

from ken.kql2.service import search

BOTH_REFERENCES = '''class Config {
    int value;
public:
    Config() : value(1) {}
    Config(const Config& other) : value(other.value) {}
    Config(Config&& other) : value(other.value) {}
};
'''


def matching_params(source, clause):
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / 'prototype.cpp').write_text(source)
    query = 'language "kql/2"; module t; query q { ' + clause + ' select $source; }'
    return search(directory, query, cache_mb=0)['rows']


def test_reference_kind_separates_the_copy_parameter_from_the_move():
    lvalue = matching_params(BOTH_REFERENCES, 'param $source { reference_kind: "lvalue"; }')
    rvalue = matching_params(BOTH_REFERENCES, 'param $source { reference_kind: "rvalue"; }')
    assert len(lvalue) == 1, lvalue
    assert len(rvalue) == 1, rvalue


def test_reference_kind_is_absent_from_a_by_value_parameter():
    source = 'class Config {\n    int value;\npublic:\n    Config(Config other) : value(other.value) {}\n};\n'
    assert not matching_params(source, 'param $source { reference_kind: "lvalue"; }')
