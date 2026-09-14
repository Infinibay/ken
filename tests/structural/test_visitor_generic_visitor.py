"""Visitor ``generic-visitor``: the visitor is chosen by type, not by an object.

The variant is a published rule, so the test goes through the registry name
``visitor#generic-visitor`` rather than a private copy of the query.

``named-dispatch`` requires ``$visitor TYPE $visitor_type`` -- a *resolvable* visitor
type -- and ``overloaded-dispatch`` requires an overload set on one. This variant is
the compile-time form: the element's method binds a type parameter of its own, the
visitor parameter is typed by that parameter, and the element passes itself to it. The
separation is complementary and asserted in both directions:

| Fixture | generic-visitor | named-dispatch |
|---|---|---|
| ``void accept(ShapeVisitor& visitor)`` | no | yes |
| ``template <typename V> void accept(V& visitor)`` | yes | no |

The ficha names one negative explicitly -- *match sin visitor separado no satisface esta
variante* -- and both spellings are covered: a C++ ``switch`` over an ``enum class`` and
a Rust ``match`` over an ``enum``. Counting cases is not a visitor.

The capability is IR 1.63. The parameter's declared type carries its decoration
(``Visitor &`` in C++, ``&V`` in Rust), which does not join to the bare type-parameter
name, so each parameter whose type *is* one of its callable's type parameters publishes
``TYPE_PARAMETER`` with the undecorated name.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'visitor#generic-visitor'
SIBLING = 'visitor#named-dispatch'
LANGUAGES = ['cpp', 'rust']
EXTENSIONS = {'cpp': 'cpp', 'rust': 'rs'}

SOURCES = {
    'cpp': '''class Circle;
class Square;

class ShapeVisitor {
public:
    virtual void visitCircle(Circle& circle) = 0;
    virtual void visitSquare(Square& square) = 0;
};

class Circle {
public:
    template <typename Visitor>
    void accept(Visitor& visitor) {
        visitor.visitCircle(*this);
    }
};

class Square {
public:
    template <typename Visitor>
    void accept(Visitor& visitor) {
        visitor.visitSquare(*this);
    }
};
''',
    'rust': '''trait ShapeVisitor {
    fn visit_circle(&self, circle: &Circle);
    fn visit_square(&self, square: &Square);
}

struct Circle;
struct Square;

impl Circle {
    fn accept<V: ShapeVisitor>(&self, visitor: &V) {
        visitor.visit_circle(self);
    }
}

impl Square {
    fn accept<V: ShapeVisitor>(&self, visitor: &V) {
        visitor.visit_square(self);
    }
}
''',
}

# The same dispatch with a resolvable visitor type: the sibling variant's case.
CONCRETE = {
    'cpp': '''class Circle;

class ShapeVisitor {
public:
    virtual void visitCircle(Circle& circle) = 0;
};

class Circle {
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visitCircle(*this);
    }
};
''',
    'rust': '''trait ShapeVisitor {
    fn visit_circle(&self, circle: &Circle);
}

struct Circle;

impl Circle {
    fn accept(&self, visitor: &dyn ShapeVisitor) {
        visitor.visit_circle(self);
    }
}
''',
}

CPP_PARAMETER_UNTIED = '''class Circle;

class ShapeVisitor {
public:
    virtual void visitCircle(Circle& circle) = 0;
};

template <typename Other>
class Circle {
public:
    void accept(ShapeVisitor& visitor) {
        visitor.visitCircle(*this);
    }
};
'''

CPP_DOES_NOT_PASS_SELF = '''class Circle;

class ShapeVisitor {
public:
    virtual void visitCircle(Circle& circle) = 0;
};

template <typename Visitor>
void run(Visitor& visitor, Circle& target) {
    visitor.visitCircle(target);
}
'''

CPP_SWITCH_WITHOUT_VISITOR = '''enum class Shape { Circle, Square };

double area(Shape shape) {
    switch (shape) {
        case Shape::Circle:
            return 1.0;
        case Shape::Square:
            return 2.0;
    }
    return 0.0;
}
'''

RUST_MATCH_WITHOUT_VISITOR = '''enum Shape {
    Circle(f64),
    Square(f64),
}

fn area(shape: &Shape) -> f64 {
    match shape {
        Shape::Circle(radius) => radius * radius,
        Shape::Square(side) => side * side,
    }
}
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'visitor')
    return next(v for v in rule.variants if v['id'] == 'generic-visitor')


def detect(language, source, rule=RULE):
    graph = link_project([lower_source(source, language, f'visitor.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_generic_visitor_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 2, language  # Circle and Square
    bindings = matches[0]['bindings']
    # The shared role with the sibling variants is the element.
    assert '/CLASS:' in bindings['$unit']
    assert '/PARAMETER:visitor' in bindings['$visitor']
    assert bindings['$visitor_parameter'] in {'V', 'Visitor'}


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_types_preserves_detection(language):
    renamed = (SOURCES[language].replace('ShapeVisitor', 'Renderer')
               .replace('Circle', 'Dot').replace('Square', 'Box')
               .replace('visitCircle', 'visitDot').replace('visitSquare', 'visitBox')
               .replace('visit_circle', 'visit_dot').replace('visit_square', 'visit_box'))
    assert detect(language, renamed), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_two_visitor_variants_are_complementary(language):
    """A resolvable visitor type is what this variant does *not* have."""
    assert detect(language, SOURCES[language], RULE), language
    assert not detect(language, SOURCES[language], SIBLING), language
    assert detect(language, CONCRETE[language], SIBLING), language
    assert not detect(language, CONCRETE[language], RULE), language


def test_a_type_parameter_that_does_not_type_the_visitor_is_rejected():
    """The method may be generic without the visitor being the parameter."""
    assert not detect('cpp', CPP_PARAMETER_UNTIED)


def test_an_element_that_does_not_pass_itself_is_rejected():
    assert not detect('cpp', CPP_DOES_NOT_PASS_SELF)


def test_a_switch_without_a_separate_visitor_is_not_this_variant():
    """The negative the ficha names: counting cases is not a visitor."""
    assert not detect('cpp', CPP_SWITCH_WITHOUT_VISITOR)
    assert not detect('rust', RUST_MATCH_WITHOUT_VISITOR)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'TYPE_PARAMETER' in row['query'] and 'INSTANCE_RECEIVER' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_visit_parameter_publishes_the_undecorated_parameter_name(language):
    """IR 1.63: ``Visitor &`` and ``&V`` are decorated, the parameter name is not.

    Without the undecorated fact the parameter's ``TYPE_NAME`` cannot join to the
    method's ``BINDS_TYPE_PARAMETER``, and the query silently matches nothing.
    """
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'visitor.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    bound = {f.object for f in graph.facts if f.relation == 'BINDS_TYPE_PARAMETER'}
    types = {f.object for f in graph.facts if f.relation == 'TYPE_PARAMETER'}
    assert bound, 'the fixture must bind a type parameter'
    assert types, 'the parameter must publish the parameter it stands for'
    assert types <= bound, (types, bound)
    decorated = {f.object for f in graph.facts
                 if f.relation == 'TYPE_NAME' and 'PARAMETER:visitor' in f.subject}
    assert decorated, 'the parameter must have a declared type'
    assert not decorated & bound, 'the declared type keeps its decoration'
