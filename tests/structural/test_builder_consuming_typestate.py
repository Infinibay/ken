"""Builder ``consuming-typestate``: a step moves the builder to another state.

The variant is a published rule, so the test goes through the registry name
``builder#consuming-typestate`` rather than a private copy of the query.

The ficha offers a disjunction -- *the step changes state parameters **or** moves the
builder* -- and this implementation takes the first side, because it is the one that is
uniform across the three languages. The step's declared return type is an **instantiation
of the builder itself**, and the argument it is applied to differs from the builder's own
parameter name: ``Builder<Pending>`` becomes ``Builder<Ready>``. The second side is not
required and not proven: C++ records ``ref_qualifier: '&&'`` on the method, but Rust does
not record receiver ownership (``self`` vs ``&self``) and TypeScript has no ownership at
all.

Requiring **two** distinct admitted states is what makes this a transition rather than a
generic fluent builder that returns itself, and `query_claim` states it. The finish is
pinned positively instead, by requiring it to yield the builder's accumulated slot --
without which the match set is a spurious step-by-finish cross product.

The capability is IR 1.65: a method whose return type applies its own declaring type
publishes ``RETURN_TYPE_ARGUMENT`` with the argument. The generic spelling survives in
``native_return_type`` (``Builder<Ready>``) but the bare type name does not carry it, and
nothing else in the graph could recover which state a step moved to.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'builder#consuming-typestate'
LANGUAGES = ['rust', 'cpp', 'typescript']
EXTENSIONS = {'rust': 'rs', 'cpp': 'cpp', 'typescript': 'ts'}

SOURCES = {
    'rust': '''struct Pending;
struct Ready;

struct Builder<State> { accumulated: i32, state: State }

impl Builder<Pending> {
    fn new() -> Builder<Pending> { Builder { accumulated: 0, state: Pending } }
    fn with_value(self, input: i32) -> Builder<Pending> { Builder { accumulated: input, state: Pending } }
    fn ready(self) -> Builder<Ready> { Builder { accumulated: self.accumulated, state: Ready } }
}

impl Builder<Ready> {
    fn finish(self) -> i32 { self.accumulated }
}
''',
    'cpp': '''struct Pending {};
struct Ready {};

template <typename State>
class Builder {
    int accumulated;
public:
    Builder<Pending> with_value(int input) && { accumulated = input; return Builder<Pending>(); }
    Builder<Ready> ready() && { return Builder<Ready>(); }
    int finish() { return accumulated; }
};
''',
    'typescript': '''class Pending { private tag: undefined; }
class Ready { private tag: undefined; }

class Builder<State> {
  private accumulated: number = 0;
  reset(): Builder<Pending> { return new Builder<Pending>(); }
  withValue(value: number): Builder<State> { this.accumulated = value; return this; }
  ready(): Builder<Ready> { return new Builder<Ready>(); }
  finish(): number { return this.accumulated; }
}
''',
}

# The same builder without a shared field for the finish to yield.
RUST_FINISH_WITHOUT_SLOT = '''struct Pending;
struct Ready;

struct Builder<State> { accumulated: i32, state: State }

impl Builder<Pending> {
    fn new() -> Builder<Pending> { Builder { accumulated: 0, state: Pending } }
    fn ready(self) -> Builder<Ready> { Builder { accumulated: self.accumulated, state: Ready } }
}

impl Builder<Ready> {
    fn finish(self) -> i32 { 0 }
}
'''

RUST_SINGLE_STATE = '''struct Builder<State> { accumulated: i32, state: State }

impl Builder<State> {
    fn with_value(self, input: i32) -> Builder<State> { Builder { accumulated: input, state: self.state } }
    fn finish(self) -> i32 { self.accumulated }
}
'''

RUST_NOT_GENERIC = '''struct Plain { accumulated: i32 }

impl Plain {
    fn with_value(self, input: i32) -> Plain { Plain { accumulated: input } }
    fn finish(self) -> i32 { self.accumulated }
}
'''

CPP_SINGLE_STATE = '''struct Pending {};

template <typename State>
class Builder {
    int accumulated;
public:
    Builder<Pending> with_value(int input) && { accumulated = input; return Builder<Pending>(); }
    int finish() { return accumulated; }
};
'''

TS_NO_STATE_CHANGE = '''class Builder<State> {
  private accumulated: number = 0;
  withValue(value: number): Builder<State> { this.accumulated = value; return this; }
  finish(): number { return this.accumulated; }
}
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'builder')
    return next(v for v in rule.variants if v['id'] == 'consuming-typestate')


def detect(language, source):
    graph = link_project([lower_source(source, language, f'builder.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_step_that_moves_the_state_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 2, language  # one per admitted state
    bindings = matches[0]['bindings']
    # The roles the rule's root query binds, plus the state witness.
    assert '/CLASS:Builder' in bindings['$builder']
    assert '/CALLABLE:finish' in bindings['$finish']
    assert bindings['$state'] in {'Pending', 'Ready'}


@pytest.mark.parametrize('language', LANGUAGES)
def test_both_admitted_states_are_reported(language):
    states = {m['bindings']['$state'] for m in detect(language, SOURCES[language])}
    assert states == {'Pending', 'Ready'}, (language, states)


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_states_and_the_builder_preserves_detection(language):
    assert detect(language, RENAMED[language]), language


def test_a_fluent_builder_that_never_changes_state_is_rejected():
    """Returning ``Builder<State>`` is a generic fluent builder, not a typestate."""
    assert not detect('rust', RUST_SINGLE_STATE)
    assert not detect('cpp', CPP_SINGLE_STATE)
    assert not detect('typescript', TS_NO_STATE_CHANGE)


def test_a_builder_that_is_not_generic_is_rejected():
    assert not detect('rust', RUST_NOT_GENERIC)


def test_a_finish_that_does_not_yield_the_accumulated_slot_is_rejected():
    assert not detect('rust', RUST_FINISH_WITHOUT_SLOT)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'type_parameter $local_state_parameter;' in row['query']
    assert 'return_type: applied($builder, $state);' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_return_type_argument_is_recorded(language):
    """IR 1.65: the bare type name cannot say which state the step moved to."""
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'builder.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    arguments = {f.object for f in graph.facts if f.relation == 'RETURN_TYPE_ARGUMENT'}
    # The two states of the transition are recorded; TypeScript also has a step that
    # returns the parameter itself, which is deliberately not a state.
    assert {'Pending', 'Ready'} <= arguments, arguments


# Renamed by construction: substituting strings over three languages produces invalid
# source long before it produces a renamed fixture.
RENAMED = {
    'rust': '''struct Idle;
struct Armed;

struct Assembly<Phase> { total: i32, phase: Phase }

impl Assembly<Idle> {
    fn start() -> Assembly<Idle> { Assembly { total: 0, phase: Idle } }
    fn add(self, input: i32) -> Assembly<Idle> { Assembly { total: input, phase: Idle } }
    fn arm(self) -> Assembly<Armed> { Assembly { total: self.total, phase: Armed } }
}

impl Assembly<Armed> {
    fn build(self) -> i32 { self.total }
}
''',
    'cpp': '''struct Idle {};
struct Armed {};

template <typename Phase>
class Assembly {
    int total;
public:
    Assembly<Idle> add(int input) && { total = input; return Assembly<Idle>(); }
    Assembly<Armed> arm() && { return Assembly<Armed>(); }
    int build() { return total; }
};
''',
    'typescript': '''class Idle { private tag: undefined; }
class Armed { private tag: undefined; }

class Assembly<Phase> {
  private total: number = 0;
  reset(): Assembly<Idle> { return new Assembly<Idle>(); }
  add(value: number): Assembly<Phase> { this.total = value; return this; }
  arm(): Assembly<Armed> { return new Assembly<Armed>(); }
  build(): number { return this.total; }
}
''',
}
