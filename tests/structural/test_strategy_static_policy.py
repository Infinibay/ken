"""Strategy ``static-policy``: the policy is chosen by type, not by an object.

The variant is a published rule, so the test goes through the registry name
``strategy#static-policy`` rather than a private copy of the query.

``strategy-object`` already covers a context holding a contract-typed field with two
implementations to choose between at run time. This variant is the ficha's *policy by
type*: the context declares a **type parameter**, a field of it is typed by that
parameter, and a method delegates through that field. `query_claim` says it plainly --
no contract, no subtype and no implementation count is required, because requiring any
of them would be requiring a runtime object.

The capability is IR 1.62. Rust already bound its type parameters
(``struct Context<P>``); C++ did not, because the grammar wraps the declaration in a
``template_declaration`` whose parameter group is the ``parameters`` field with
``type_parameter_declaration`` members, while ``bound_type_parameters`` looked only for
a ``type_parameters`` field. Both are bound now, and each declaration publishes
``BINDS_TYPE_PARAMETER`` -- a *fact*, because an attribute list is not reachable from
KenQL and the field's ``TYPE_NAME`` has to be joinable to the parameter it stands for.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'strategy#static-policy'
SIBLING = 'strategy#strategy-object'
LANGUAGES = ['cpp', 'rust']
EXTENSIONS = {'cpp': 'cpp', 'rust': 'rs'}

SOURCES = {
    'cpp': '''struct FastPolicy {
    int compute(int value) { return value * 2; }
};

template <typename Policy>
class Context {
    Policy policy;
public:
    int run(int value) {
        return policy.compute(value);
    }
};

int main() {
    Context<FastPolicy> context;
    return context.run(1);
}
''',
    'rust': '''trait Policy {
    fn compute(&self, value: i32) -> i32;
}

struct FastPolicy;

impl Policy for FastPolicy {
    fn compute(&self, value: i32) -> i32 { value * 2 }
}

struct Context<P: Policy> {
    policy: P,
}

impl<P: Policy> Context<P> {
    fn run(&self, value: i32) -> i32 {
        self.policy.compute(value)
    }
}
''',
}

CPP_CONCRETE_FIELD = '''struct FastPolicy {
    int compute(int value) { return value * 2; }
};

class Context {
    FastPolicy policy;
public:
    int run(int value) {
        return policy.compute(value);
    }
};
'''

CPP_PARAMETER_UNUSED_AS_FIELD = '''template <typename Policy>
class Context {
    int value;
public:
    int run(int input) {
        return value + input;
    }
};
'''

CPP_FIELD_WITHOUT_DELEGATION = '''template <typename Policy>
class Context {
    Policy policy;
public:
    int run(int value) {
        return value;
    }
};
'''

CPP_PARAMETER_ONLY_IN_SIGNATURE = '''template <typename Policy>
class Context {
public:
    int run(Policy policy) {
        return 1;
    }
};
'''

CPP_PARAMETER_ON_ANOTHER_TYPE = '''struct FastPolicy { int compute(int v) { return v; } };

template <typename Policy>
class Other {};

class Context {
    FastPolicy policy;
public:
    int run(int value) { return policy.compute(value); }
};
'''

RUST_CONCRETE_FIELD = '''trait Policy { fn compute(&self, value: i32) -> i32; }
struct FastPolicy;
impl Policy for FastPolicy { fn compute(&self, value: i32) -> i32 { value * 2 } }

struct Context { policy: FastPolicy }

impl Context {
    fn run(&self, value: i32) -> i32 { self.policy.compute(value) }
}
'''

RUST_PARAMETER_UNUSED_AS_FIELD = '''struct Context<P> { value: i32 }

impl<P> Context<P> {
    fn run(&self, input: i32) -> i32 { self.value + input }
}
'''

RUST_FIELD_WITHOUT_DELEGATION = '''struct Context<P> { policy: P }

impl<P> Context<P> {
    fn run(&self, value: i32) -> i32 { value }
}
'''

RUST_PARAMETER_ONLY_IN_SIGNATURE = '''struct Context<P> { value: i32 }

impl<P> Context<P> {
    fn run(&self, policy: P, value: i32) -> i32 { self.value + value }
}
'''

CPP_QUALIFIED_PARAMETER_CALL = '''struct Policy {
    static int apply(int x) { return x + 1; }
};

template <class P>
struct Algorithm {
    int run(int x) { return P::apply(x); }
};
'''

CPP_QUALIFIED_CONCRETE_CALL = '''struct Policy {
    static int apply(int x) { return x + 1; }
};

struct Algorithm {
    int run(int x) { return Policy::apply(x); }
};
'''

CPP_QUALIFIED_WITHOUT_INVOCATION = '''template <class P>
struct Algorithm {
    int run(int x) { return x; }
};
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'strategy')
    return next(v for v in rule.variants if v['id'] == 'static-policy')


def detect(language, source, rule=RULE):
    graph = link_project([lower_source(source, language, f'strategy.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_type_parameter_policy_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variants is the context.
    assert '/CLASS:Context' in bindings['$unit']
    assert '/STORAGE:policy' in bindings['$policy']
    assert bindings['$parameter'] in {'P', 'Policy'}
    assert bindings['$algorithm'] != bindings['$policy']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_types_preserves_detection(language):
    renamed = (SOURCES[language].replace('Context', 'Host').replace('FastPolicy', 'QuickPolicy')
               .replace('Policy', 'Rule').replace('compute', 'evaluate').replace('run', 'execute'))
    assert detect(language, renamed), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_concrete_field_type_is_not_a_static_policy(language):
    """Without a type parameter this is just a field of one known type."""
    source = CPP_CONCRETE_FIELD if language == 'cpp' else RUST_CONCRETE_FIELD
    assert not detect(language, source), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_type_parameter_that_does_not_type_the_field_is_rejected(language):
    source = CPP_PARAMETER_UNUSED_AS_FIELD if language == 'cpp' else RUST_PARAMETER_UNUSED_AS_FIELD
    assert not detect(language, source), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_field_of_the_parameter_without_delegation_is_rejected(language):
    source = CPP_FIELD_WITHOUT_DELEGATION if language == 'cpp' else RUST_FIELD_WITHOUT_DELEGATION
    assert not detect(language, source), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_type_parameter_used_only_in_the_signature_is_rejected(language):
    source = CPP_PARAMETER_ONLY_IN_SIGNATURE if language == 'cpp' else RUST_PARAMETER_ONLY_IN_SIGNATURE
    assert not detect(language, source), language


def test_the_parameter_must_belong_to_the_unit_that_holds_the_field():
    assert not detect('cpp', CPP_PARAMETER_ON_ANOTHER_TYPE)


@pytest.mark.parametrize('language', LANGUAGES)
def test_no_runtime_object_is_required(language):
    """The separation from strategy-object, which needs a contract and two subtypes.

    Neither fixture declares a subtype relation or more than one candidate
    implementation, so the sibling variant must not match them.
    """
    assert not detect(language, SOURCES[language], SIBLING), language


def test_a_qualified_type_parameter_call_is_a_static_policy():
    """The ficha's second form: ``P::apply(x)`` with no stored object.

    ``query_claim`` says the policy role is "the field or the type parameter,
    according to the form", so authoring against the field alone loses half the
    pattern. Here the call is qualified by the declaration's own generic
    parameter, which the frontend accredits as ``TYPE_PARAMETER_RECEIVER``.
    """
    matches = detect('cpp', CPP_QUALIFIED_PARAMETER_CALL)
    assert len(matches) == 1
    bindings = matches[0]['bindings']
    assert '/CLASS:Algorithm' in bindings['$unit']
    assert bindings['$policy'] == bindings['$parameter']
    assert bindings['$parameter'] in {'P'}
    assert bindings['$algorithm'] != bindings['$policy']


def test_a_qualified_call_to_a_concrete_type_is_not_a_static_policy():
    """``Policy::apply(x)`` names a known type, so nothing is chosen by type."""
    assert not detect('cpp', CPP_QUALIFIED_CONCRETE_CALL)


def test_a_type_parameter_that_is_not_invoked_is_not_a_static_policy():
    assert not detect('cpp', CPP_QUALIFIED_WITHOUT_INVOCATION)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    # The published query must bind the declaration's type parameter and compare
    # it with the field's type name. KQL 2 spells those two steps
    # ``type_parameter $t;`` and ``type: parameter($t)``.
    assert 'type_parameter' in row['query']
    assert 'parameter(' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_both_languages_bind_their_type_parameters(language):
    """IR 1.62: C++ bound none before, because its group is spelled differently.

    The declaration publishes the binding as a fact, and the field's ``TYPE_NAME`` is
    the parameter's name, so the two join without resolving the instantiation.
    """
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'strategy.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    context = next(e.id for e in graph.entities.values()
                   if e.kind == 'CLASS' and e.name == 'Context')
    bound = {f.object for f in graph.facts
             if f.relation == 'BINDS_TYPE_PARAMETER' and f.subject == context}
    assert bound, context
    assert graph.entities[context].attrs.get('type_parameters') == sorted(bound)
    field = next(e for e in graph.entities.values()
                 if e.kind == 'STORAGE' and e.name == 'policy')
    names = {f.object for f in graph.facts
             if f.relation == 'TYPE_NAME' and f.subject == field.id}
    assert names & bound, (names, bound)
