"""Bridge ``generic-composition``: the implementation is a shared type parameter.

The variant is a published rule, so the test goes through the registry name
``bridge#generic-composition`` rather than a private copy of the query.

``runtime-composition`` covers an abstraction holding an implementation by contract at
run time. This variant is the compile-time form, and the ficha is explicit that it must
not require virtual dispatch: nothing here asks for a subtype, an interface or more than
one implementation.

The evidence that separates it from ``strategy#static-policy`` -- which reads the very
same field shape -- is that the type abstraction has a **connected generic refinement**. One
context holding one policy is a strategy; the generic abstraction with nominal
refinements or refinements holding it provides the second dimension of Bridge. That separation is asserted in both
directions.

The second declaration must inherit the abstraction or hold a field of its type.
An unrelated generic declaration no longer satisfies the contract merely because
both parameters happen to be spelled I or T. A refinement may rename its parameter.

The capability is IR 1.64. Type parameters were bound for Rust and C++ only since
1.62; TypeScript, Java, C# and Go bound none, even though their grammars spell the
group. C# needed one more thing than the others: it leaves ``type_parameter_list``
unfielded, so it is found by node type among the declaration's own children. Go needed
a different fix -- a generic receiver spells its type arguments (``*Abstraction[I]``)
and the declaration is named without them, so the method was being owned by the module
instead of by its type.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'bridge#generic-composition'
SIBLING = 'strategy#static-policy'
LANGUAGES = ['typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'typescript': 'ts', 'java': 'java', 'csharp': 'cs', 'cpp': 'cpp',
              'go': 'go', 'rust': 'rs'}

SOURCES = {
    'typescript': '''class Abstraction<I> {
  protected impl: I;
  constructor(impl: I) { this.impl = impl; }
  operation(): string { return this.impl.run(); }
}

class Refined<I> extends Abstraction<I> {
  operation(): string { return this.impl.run(); }
}
''',
    'java': '''class Abstraction<I> {
    protected I impl;
    Abstraction(I impl) { this.impl = impl; }
    String operation() { return this.impl.run(); }
}

class Refined<I> extends Abstraction<I> {
    Refined(I impl) { super(impl); }
    String operation() { return this.impl.run(); }
}
''',
    'csharp': '''class Abstraction<I> {
    protected I impl;
    public Abstraction(I impl) { this.impl = impl; }
    public string Operation() { return this.impl.Run(); }
}

class Refined<I> : Abstraction<I> {
    public Refined(I impl) : base(impl) { }
    public string Operation() { return this.impl.Run(); }
}
''',
    'cpp': '''template <typename I>
class Abstraction {
protected:
    I impl;
public:
    Abstraction(I value) : impl(value) {}
    int operation() { return impl.run(); }
};

template <typename I>
class Refined : public Abstraction<I> {
public:
    Refined(I value) : Abstraction<I>(value) {}
    int operation() { return this->impl.run(); }
};
''',
    'go': '''package bridge

type Abstraction[I any] struct {
\timpl I
}

func (a *Abstraction[I]) Operation() int {
\treturn a.impl.Run()
}

type Refined[I any] struct {
\tinner Abstraction[I]
}

func (r *Refined[I]) Operation() int {
\treturn r.inner.Operation()
}
''',
    'rust': '''struct Abstraction<I> { impl_value: I }

impl<I> Abstraction<I> {
    fn operation(&self) -> i32 {
        self.impl_value.run()
    }
}

struct Refined<I> { inner: Abstraction<I> }
''',
}

# One context holding one policy: the sibling variant's case, and not a bridge.
JAVA_SINGLE = '''class Abstraction<I> {
    protected I impl;
    Abstraction(I impl) { this.impl = impl; }
    String operation() { return this.impl.run(); }
}
'''

TS_PARAMETER_NOT_SHARED = '''class Abstraction<I> {
  protected impl: I;
  constructor(impl: I) { this.impl = impl; }
  operation(): string { return this.impl.run(); }
}

class Refined<J> {
  protected other: J;
}
'''

JAVA_CONCRETE_FIELD = '''class Impl { String run() { return ""; } }

class Abstraction<I> {
    protected Impl impl;
    Abstraction(Impl impl) { this.impl = impl; }
    String operation() { return this.impl.run(); }
}

class Refined<I> extends Abstraction<I> {
    Refined(Impl impl) { super(impl); }
}
'''

JAVA_NO_DELEGATION = '''class Abstraction<I> {
    protected I impl;
    Abstraction(I impl) { this.impl = impl; }
    String operation() { return "fixed"; }
}

class Refined<I> extends Abstraction<I> {
    Refined(I impl) { super(impl); }
}
'''

GO_NON_GENERIC_RECEIVER = '''package bridge

type Backend struct{}

func (b *Backend) Run() int { return 1 }

type Abstraction[I any] struct {
\timpl I
}

func (a *Abstraction[I]) Operation() int {
\treturn a.impl.Run()
}

type Refined[I any] struct {
\tinner Abstraction[I]
}

func (r *Refined[I]) Operation() int {
\treturn r.inner.Operation()
}
'''


# The same shape with different names, built per language rather than substituted.
RENAMED = {
    'typescript': '''class Core<T> {
  protected delegate: T;
  constructor(delegate: T) { this.delegate = delegate; }
  execute(): string { return this.delegate.run(); }
}

class Extended<T> extends Core<T> {
  execute(): string { return this.delegate.run(); }
}
''',
    'java': '''class Core<T> {
    protected T delegate;
    Core(T delegate) { this.delegate = delegate; }
    String execute() { return this.delegate.run(); }
}

class Extended<T> extends Core<T> {
    Extended(T delegate) { super(delegate); }
    String execute() { return this.delegate.run(); }
}
''',
    'csharp': '''class Core<T> {
    protected T inner;
    public Core(T inner) { this.inner = inner; }
    public string Execute() { return this.inner.Run(); }
}

class Extended<T> : Core<T> {
    public Extended(T inner) : base(inner) { }
    public string Execute() { return this.inner.Run(); }
}
''',
    'cpp': '''template <typename T>
class Core {
protected:
    T delegate;
public:
    Core(T value) : delegate(value) {}
    int execute() { return delegate.run(); }
};

template <typename T>
class Extended : public Core<T> {
public:
    Extended(T value) : Core<T>(value) {}
    int execute() { return this->delegate.run(); }
};
''',
    'go': '''package bridge

type Core[T any] struct {
\tdelegate T
}

func (c *Core[T]) Execute() int {
\treturn c.delegate.Run()
}

type Extended[T any] struct {
\tinner Core[T]
}

func (e *Extended[T]) Execute() int {
\treturn e.inner.Execute()
}
''',
    'rust': '''struct Core<T> { delegate_value: T }

impl<T> Core<T> {
    fn execute(&self) -> i32 {
        self.delegate_value.run()
    }
}

struct Extended<T> { inner: Core<T> }
''',
}


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'bridge')
    return next(v for v in rule.variants if v['id'] == 'generic-composition')


def detect(language, source, rule=RULE):
    graph = link_project([lower_source(source, language, f'bridge.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_shared_implementation_parameter_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variants is the abstraction.
    assert '/CLASS:' in bindings['$unit']
    assert '/STORAGE:' in bindings['$implementation']
    assert bindings['$implementation_parameter'] == 'I'


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_types_and_the_parameter_preserves_detection(language):
    # Constructed rather than substituted: a replace chain over six languages and two
    # syntaxes produces invalid source long before it produces a renamed fixture.
    assert detect(language, RENAMED[language]), language


def test_a_single_generic_type_is_a_strategy_not_a_bridge():
    """The separation: one type binding the parameter is the sibling's case.

    Both variants read the same field shape; only the sharing of the parameter
    distinguishes them, and it is asserted in both directions.
    """
    assert detect('java', JAVA_SINGLE, SIBLING)
    assert not detect('java', JAVA_SINGLE, RULE)


def test_a_parameter_that_is_not_shared_is_rejected():
    assert not detect('typescript', TS_PARAMETER_NOT_SHARED)


def test_a_concrete_implementation_field_is_rejected():
    assert not detect('java', JAVA_CONCRETE_FIELD)


def test_an_abstraction_that_does_not_delegate_is_rejected():
    assert not detect('java', JAVA_NO_DELEGATION)


def test_a_non_generic_go_receiver_is_not_disturbed():
    """The receiver fix must not turn an ordinary method into a generic one."""
    graph = link_project([lower_source(GO_NON_GENERIC_RECEIVER, 'go', 'bridge.go')])
    assert not graph.diagnostics, graph.diagnostics
    backend = next(e.id for e in graph.entities.values()
                   if e.kind == 'CLASS' and e.name == 'Backend')
    assert graph.entities[backend].attrs.get('type_parameters') in (None, [])
    assert detect('go', GO_NON_GENERIC_RECEIVER)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'type_parameter $implementation_parameter;' in row['query']
    assert 'type: parameter($implementation_parameter);' in row['query']
    assert 'where subtype($local_variant, $unit);' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_every_language_binds_its_type_parameters(language):
    """IR 1.64: four of the six bound none before, despite spelling the group."""
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'bridge.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    types = {e.id for e in graph.entities.values() if e.kind in {'CLASS', 'INTERFACE'}}
    binding_types = {f.subject for f in graph.facts
                     if f.relation == 'BINDS_TYPE_PARAMETER' and f.subject in types}
    assert len(binding_types) >= 2, binding_types


def test_a_generic_go_receiver_owns_its_method():
    """``*Abstraction[I]`` names ``Abstraction``, so the method is not module-owned."""
    graph = link_project([lower_source(SOURCES['go'], 'go', 'bridge.go')])
    assert not graph.diagnostics, graph.diagnostics
    abstraction = next(e.id for e in graph.entities.values()
                       if e.kind == 'CLASS' and e.name == 'Abstraction')
    methods = {f.object for f in graph.facts
               if f.relation == 'HAS_METHOD' and f.subject == abstraction}
    assert methods, 'the generic receiver method must belong to its type'
