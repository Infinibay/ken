"""Visitor ``overloaded-dispatch``: the visitor's operation is an overload set.

The variant is a published rule, so the test goes through the registry name
``visitor#overloaded-dispatch`` rather than a private copy of the query.

``named-dispatch`` already covers "the element passes itself to a visitor operation",
and it requires ``$dispatch TARGET $visit`` -- a *resolved* target. This variant is its
twin for the case where the target cannot resolve because the visitor declares several
operations of that name. The separation is exact and both directions are asserted in
``test_the_two_visitor_variants_are_complementary``:

| Fixture | TARGET facts | named-dispatch | overloaded-dispatch |
|---|---|---|---|
| visitor with one operation | resolves | yes | no |
| visitor with an overload set | none | no | yes |

The contract counts the visitor's same-named operations with a **lower bound**
(``>= 2``), not an exact cardinality: an overload set with three members is still an
overload set, and a lower bound needs no closed-world capability.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'visitor#overloaded-dispatch'
SIBLING = 'visitor#named-dispatch'
LANGUAGES = ['java', 'csharp', 'cpp']
EXTENSIONS = {'java': 'java', 'csharp': 'cs', 'cpp': 'cpp'}

OVERLOADED = {
    'java': '''interface ShapeVisitor {
    void visit(Circle circle);
    void visit(Square square);
}

class Circle {
    void accept(ShapeVisitor visitor) {
        visitor.visit(this);
    }
}

class Square {
    void accept(ShapeVisitor visitor) {
        visitor.visit(this);
    }
}
''',
    'csharp': '''interface IShapeVisitor {
    void Visit(Circle circle);
    void Visit(Square square);
}

class Circle {
    public void Accept(IShapeVisitor visitor) {
        visitor.Visit(this);
    }
}

class Square {
    public void Accept(IShapeVisitor visitor) {
        visitor.Visit(this);
    }
}
''',
    'cpp': '''class Circle;
class Square;

class ShapeVisitor {
public:
    virtual void visit(Circle& circle) = 0;
    virtual void visit(Square& square) = 0;
};

class Circle {
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visit(*this);
    }
};

class Square {
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visit(*this);
    }
};
''',
}

# The same elements against a visitor with a single operation: the twin variant's case.
SINGLE = {
    'java': '''interface ShapeVisitor {
    void visit(Circle circle);
}

class Circle {
    void accept(ShapeVisitor visitor) {
        visitor.visit(this);
    }
}
''',
    'csharp': '''interface IShapeVisitor {
    void Visit(Circle circle);
}

class Circle {
    public void Accept(IShapeVisitor visitor) {
        visitor.Visit(this);
    }
}
''',
    'cpp': '''class Circle;

class ShapeVisitor {
public:
    virtual void visit(Circle& circle) = 0;
};

class Circle {
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visit(*this);
    }
};
''',
}

JAVA_SELF_NOT_PASSED = '''interface ShapeVisitor {
    void visit(Circle circle);
    void visit(Square square);
}

class Circle {
    void accept(ShapeVisitor visitor, Circle other) {
        visitor.visit(other);
    }
}
'''

JAVA_UNDER_ANOTHER_NAME = '''interface ShapeVisitor {
    void visit(Circle circle);
    void visit(Square square);
    void handle(Circle circle);
}

class Circle {
    void accept(ShapeVisitor visitor) {
        visitor.handle(this);
    }
}
'''

JAVA_RECEIVER_IS_A_FIELD = '''interface ShapeVisitor {
    void visit(Circle circle);
    void visit(Square square);
}

class Circle {
    private ShapeVisitor stored;

    void accept(ShapeVisitor visitor) {
        stored.visit(this);
    }
}
'''

JAVA_NEVER_CALLS = '''interface ShapeVisitor {
    void visit(Circle circle);
    void visit(Square square);
}

class Circle {
    void accept(ShapeVisitor visitor) {
        int ignored = 1;
    }
}
'''

JAVA_OVERLOADS_ON_ANOTHER_TYPE = '''interface ShapeVisitor {
    void visit(Circle circle);
}

class Overloaded {
    void visit(Circle circle) {}
    void visit(Square square) {}
}

class Circle {
    void accept(ShapeVisitor visitor) {
        visitor.visit(this);
    }
}
'''

CPP_SELF_NOT_PASSED = '''class Circle;
class Square;

class ShapeVisitor {
public:
    virtual void visit(Circle& circle) = 0;
    virtual void visit(Square& square) = 0;
};

class Circle {
    Circle& other;
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visit(other);
    }
};
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'visitor')
    return next(v for v in rule.variants if v['id'] == 'overloaded-dispatch')


def detect(language, source, rule=RULE):
    graph = link_project([lower_source(source, language, f'visitor.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_an_overloaded_visitor_is_detected(language):
    matches = detect(language, OVERLOADED[language])
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variant is the element.
    assert '/CLASS:Circle' in bindings['$unit'] or '/CLASS:Square' in bindings['$unit']
    assert '/PARAMETER:visitor' in bindings['$visitor'] or '/PARAMETER:Visitor' in bindings['$visitor']
    assert '/INTERFACE:' in bindings['$visitor_type'] or '/CLASS:' in bindings['$visitor_type']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_types_preserves_detection(language):
    renamed = (OVERLOADED[language].replace('ShapeVisitor', 'Renderer')
               .replace('IShapeVisitor', 'IRenderer'))
    assert detect(language, renamed), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_two_visitor_variants_are_complementary(language):
    """An overload set is what this variant adds, and it is exactly what blocks TARGET.

    With one operation the call resolves, so the sibling variant matches and this one
    does not; with an overload set nothing resolves, and the reverse holds.
    """
    assert detect(language, OVERLOADED[language], RULE), language
    assert not detect(language, OVERLOADED[language], SIBLING), language
    assert detect(language, SINGLE[language], SIBLING), language
    assert not detect(language, SINGLE[language], RULE), language


def test_an_element_that_does_not_pass_itself_is_rejected():
    assert not detect('java', JAVA_SELF_NOT_PASSED)
    assert not detect('cpp', CPP_SELF_NOT_PASSED)


def test_overloads_under_another_name_are_rejected():
    assert not detect('java', JAVA_UNDER_ANOTHER_NAME)


def test_the_dispatch_receiver_must_be_the_visitor_parameter():
    assert not detect('java', JAVA_RECEIVER_IS_A_FIELD)


def test_a_method_that_never_calls_the_visitor_is_rejected():
    assert not detect('java', JAVA_NEVER_CALLS)


def test_the_overload_set_must_be_on_the_visitor_type():
    assert not detect('java', JAVA_OVERLOADS_ON_ANOTHER_TYPE)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'INSTANCE_RECEIVER' in row['query'] and 'count distinct' in row['query']
