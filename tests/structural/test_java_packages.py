"""Cross-file Java nominal linkage uses package identity, not global basenames."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules


def graph(sources):
    units = [lower_source(source, 'java', path) for path, source in sources.items()]
    assert not any(u.diagnostics for u in units)
    return link_project(units)


@pytest.mark.parametrize('package,reference', [
 ('package domain;', 'Base'),
 ('package client; import domain.Base;', 'Base'),
 ('package client;', 'domain.Base'),
])
def test_java_template_method_across_files(package, reference):
    g = graph({'Base.java': 'package domain; public abstract class Base { public void execute(){ step(); } public abstract void step(); }',
               'Child.java': package + ' class Child extends ' + reference + ' { public void step(){} }'})
    registry = builtin_rules()
    result = execute_rules(g, [named_rule('gof.template-method', registry)], registry=registry)
    assert result['complete']
    assert result['matches']


@pytest.mark.parametrize('imports,expected', [
 ('', False),
 ('import domain.Base;', True),
 ('import missing.Base;', False),
 ('import domain.Base; import other.Base;', False),
 ('import domain.*;', False),
])
def test_java_does_not_guess_missing_or_ambiguous_import(imports, expected):
    g = graph({'Base.java': 'package domain; class Base {}',
               'Other.java': 'package other; class Base {}',
               'Child.java': 'package client; ' + imports + ' class Child extends Base {}'})
    assert any(f.relation == 'SUBTYPE_OF' for f in g.facts) is expected


def test_duplicate_qualified_types_remain_unresolved():
    g = graph({'one/Base.java': 'package domain; class Base {}',
               'two/Base.java': 'package domain; class Base {}',
               'Child.java': 'package domain; class Child extends Base {}'})
    assert not any(f.relation == 'SUBTYPE_OF' for f in g.facts)


def test_default_package_links_without_directory_assumptions():
    g = graph({'one/Base.java': 'class Base {}', 'two/Child.java': 'class Child extends Base {}'})
    assert any(f.relation == 'SUBTYPE_OF' for f in g.facts)
