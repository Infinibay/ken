import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.service import search

LIB = '''language "kql/2"; module filters;
predicate Accepted(TypeDecl $c) { $c.name == "A" }
pattern Choose(out TypeDecl $c) { class $c {} where Accepted($c); }
'''
QUERY = '''language "kql/2"; module main; import filters;
query q { use filters.Choose(c:$c); select $c.name; }'''


def test_library_edit_invalidates_plan_and_result(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass\nclass B: pass')
    first = search(tmp_path, QUERY, libraries={'filters':LIB})
    assert first['rows'] == [['A']]
    second = search(tmp_path, QUERY, libraries={'filters':LIB.replace('"A"','"B"')})
    assert second['rows'] == [['B']]
    assert second['analysis']['compilation_cache']['status'] == 'miss'
    assert second['analysis']['result_cache'] == 'miss'
    assert second['analysis']['parsed_units'] == 0


def test_transitive_and_cyclic_imports_are_resolved_without_initializers():
    library = parse(LIB.replace('module filters;', 'module filters; import second;'))
    second = parse('language "kql/2"; module second; import filters; predicate P(TypeDecl $c) { filters.Accepted($c) }')
    p = compile(parse(QUERY), libraries={'filters':library, 'second':second})
    assert {pred.name for pred in p.predicates} == {'filters.Accepted','second.P'}


def test_imported_query_does_not_steal_entry_point():
    library = parse(LIB + 'query other { select 1; }')
    assert compile(parse(QUERY), libraries={'filters':library}).name == 'q'


@pytest.mark.parametrize('libraries', [{}, {'filters':parse(LIB.replace('module filters;', 'module wrong;'))}])
def test_missing_or_mismatched_library(libraries):
    with pytest.raises(CompileError, match='library module'):
        compile(parse(QUERY), libraries=libraries)


def test_imported_model_and_signature():
    library = parse('''language "kql/2"; module filters;
      signature S { predicate accept(TypeDecl $c); }
      model M implements S { predicate accept(TypeDecl $c) { true } }
      pattern P<T: S>(out TypeDecl $c) { class $c {} where T.accept($c); }
    ''')
    entry = parse('language "kql/2"; module main; import filters; query q { use filters.P<filters.M>(c:$c); select $c; }')
    assert compile(entry, libraries={'filters':library}).predicates[0].name == 'filters.M.accept'


def test_model_local_predicate_shadows_imported_global(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass\n')
    library = '''language "kql/2"; module filters;
      predicate inner(TypeDecl $c) { false }
      signature S { predicate accept(TypeDecl $c); }
      model M implements S {
        predicate inner(TypeDecl $c) { true }
        predicate accept(TypeDecl $c) { inner($c) }
      }
      pattern P<T: S>(out TypeDecl $c) { class $c {} where T.accept($c); }
    '''
    entry = 'language "kql/2"; module main; import filters; query q { use filters.P<filters.M>(c:$c); select $c.name; }'
    assert search(tmp_path,entry,libraries={'filters':library},cache_mb=0)['rows'] == [['A']]
