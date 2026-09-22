"""State ``state-enum``: a state value governs a branch and a transition rewrites it.

The variant is a published rule, so the test goes through the registry name
``state#state-enum`` rather than a private copy of the query.

What the contract refuses to require is a ``State`` object. The ficha is explicit
("no introducir objetos State ficticios"): the state is a value, and the evidence
is that a guard mentioning the field sits over a write to that same field, with at
least two distinct constants written.

The evidence is now a **cycle of two correlated transitions**: the method compares
the field with ``$observed`` and writes ``$next`` in that arm, and in the alternative
arm compares with ``$next`` and writes ``$observed`` back. BODY captures both values
from the occurrences, so the query states the machine instead of counting constants,
and the C++/Rust "one constant, two syntax positions" false positive cannot occur:
``test_writing_one_state_twice_is_not_a_transition`` pins it. A single guarded
transition is rejected (``test_a_single_guarded_transition_is_rejected``), which is
why the variant does not accept one-arm machines.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'state#state-enum'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
# Languages where the variant is claimed. C++ and Rust write ``else if`` as a branch
# nested directly in an ``else`` wrapper; BODY reaches the consequence arm of that
# nesting but not yet the alternative one, so the cycle is unmatched there and the
# gap is pinned by ``test_pending_languages_record_the_unmatched_arm_shape``.
DECLARED = ['python', 'javascript', 'typescript', 'java', 'csharp', 'go']
PENDING = ['cpp', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}

# The positive fixture and, per language, the same machine with both branches
# writing one state: syntactically a transition, structurally no change.
SOURCES = {
    'python': '''from enum import Enum

class State(Enum):
    IDLE = 1
    RUNNING = 2

class Machine:
    def __init__(self):
        self.state = State.IDLE

    def step(self):
        if self.state == State.IDLE:
            self.state = State.RUNNING
        elif self.state == State.RUNNING:
            self.state = State.IDLE
''',
    'javascript': '''const State = { IDLE: 'idle', RUNNING: 'running' };

class Machine {
  constructor() { this.state = State.IDLE; }
  step() {
    if (this.state === State.IDLE) { this.state = State.RUNNING; }
    else if (this.state === State.RUNNING) { this.state = State.IDLE; }
  }
}
''',
    'typescript': '''enum State { Idle, Running }

class Machine {
  state: State = State.Idle;
  step(): void {
    if (this.state === State.Idle) { this.state = State.Running; }
    else if (this.state === State.Running) { this.state = State.Idle; }
  }
}
''',
    'java': '''enum State { IDLE, RUNNING }

class Machine {
    private State state = State.IDLE;
    void step() {
        if (this.state == State.IDLE) { this.state = State.RUNNING; }
        else if (this.state == State.RUNNING) { this.state = State.IDLE; }
    }
}
''',
    'csharp': '''enum State { Idle, Running }

class Machine {
    private State state = State.Idle;
    public void Step() {
        if (this.state == State.Idle) { this.state = State.Running; }
        else if (this.state == State.Running) { this.state = State.Idle; }
    }
}
''',
    'cpp': '''enum class State { Idle, Running };

class Machine {
    State state = State::Idle;
public:
    void step() {
        if (state == State::Idle) { state = State::Running; }
        else if (state == State::Running) { state = State::Idle; }
    }
};
''',
    'go': '''package machine

type State int

const (
\tIdle State = iota
\tRunning
)

type Machine struct{ state State }

func (m *Machine) Step() {
\tif m.state == Idle {
\t\tm.state = Running
\t} else if m.state == Running {
\t\tm.state = Idle
\t}
}
''',
    'rust': '''#[derive(PartialEq)]
enum State { Idle, Running }

struct Machine { state: State }

impl Machine {
    fn step(&mut self) {
        if self.state == State::Idle { self.state = State::Running; }
        else if self.state == State::Running { self.state = State::Idle; }
    }
}
''',
}

NO_CHANGE = {
    'python': SOURCES['python'].replace(
        '        elif self.state == State.RUNNING:\n            self.state = State.IDLE\n',
        '        elif self.state == State.RUNNING:\n            self.state = State.RUNNING\n'),
    'javascript': SOURCES['javascript'].replace(
        'else if (this.state === State.RUNNING) { this.state = State.IDLE; }',
        'else if (this.state === State.RUNNING) { this.state = State.RUNNING; }'),
    'typescript': SOURCES['typescript'].replace(
        'else if (this.state === State.Running) { this.state = State.Idle; }',
        'else if (this.state === State.Running) { this.state = State.Running; }'),
    'java': SOURCES['java'].replace(
        'else if (this.state == State.RUNNING) { this.state = State.IDLE; }',
        'else if (this.state == State.RUNNING) { this.state = State.RUNNING; }'),
    'csharp': SOURCES['csharp'].replace(
        'else if (this.state == State.Running) { this.state = State.Idle; }',
        'else if (this.state == State.Running) { this.state = State.Running; }'),
    'cpp': SOURCES['cpp'].replace(
        'else if (state == State::Running) { state = State::Idle; }',
        'else if (state == State::Running) { state = State::Running; }'),
    'go': SOURCES['go'].replace('\t\tm.state = Idle\n', '\t\tm.state = Running\n'),
    'rust': SOURCES['rust'].replace(
        'else if self.state == State::Running { self.state = State::Idle; }',
        'else if self.state == State::Running { self.state = State::Running; }'),
}

PY_NO_GUARD = '''from enum import Enum

class State(Enum):
    IDLE = 1
    RUNNING = 2

class Machine:
    def __init__(self):
        self.state = State.IDLE

    def step(self):
        self.state = State.RUNNING
        self.state = State.IDLE
'''

PY_OTHER_FIELD = '''from enum import Enum

class State(Enum):
    IDLE = 1
    RUNNING = 2

class Machine:
    def __init__(self):
        self.state = State.IDLE
        self.other = State.IDLE

    def step(self):
        if self.state == State.IDLE:
            self.other = State.RUNNING
        elif self.state == State.RUNNING:
            self.other = State.IDLE
'''

PY_SINGLE_BRANCH = '''from enum import Enum

class State(Enum):
    IDLE = 1
    RUNNING = 2

class Machine:
    def __init__(self):
        self.state = State.IDLE

    def step(self):
        if self.state == State.IDLE:
            self.state = State.RUNNING
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'state')
    return next(v for v in rule.variants if v['id'] == 'state-enum')


def detect(language, source):
    graph = link_project([lower_source(source, language, f'state.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', DECLARED)
def test_guarded_transition_between_two_states_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role is the context, matching state-object and
    # context-transition, so all three variants agree on what ``$unit`` names.
    assert '/CLASS:' in bindings['$unit']
    assert '/STORAGE:state' in bindings['$state']
    assert bindings['$transition'] != bindings['$state']


@pytest.mark.parametrize('language', LANGUAGES)
def test_writing_one_state_twice_is_not_a_transition(language):
    """The soundness negative: a rewrite that changes nothing is not State.

    For C++ and Rust this failed before IR 1.58, because the two occurrences of
    one constant were two entities and satisfied ``count distinct >= 2``.
    """
    assert not detect(language, NO_CHANGE[language]), language


def test_a_transition_without_a_guard_is_rejected():
    """Two distinct states written, but nothing decides between them."""
    assert not detect('python', PY_NO_GUARD)


def test_a_guard_over_writes_to_another_field_is_rejected():
    assert not detect('python', PY_OTHER_FIELD)


def test_a_single_guarded_transition_is_rejected():
    assert not detect('python', PY_SINGLE_BRANCH)


def test_pending_languages_record_the_unmatched_arm_shape():
    """A measured gap, pinned so it cannot silently become a claim.

    C++/Rust ``else if`` is a branch inside an ``else`` wrapper. The consequence arm
    of that nesting matches; the alternative arm does not, so the two-transition
    cycle is not witnessed and the variant stays unclaimed there.
    """
    for language in PENDING:
        assert not detect(language, SOURCES[language]), language
        assert not detect(language, NO_CHANGE[language]), language


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == DECLARED
    assert row.get('pending_languages') == PENDING
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    # The KQL 2 evidence: the guard is a BODY branch and the transition is the
    # compared/written pair, so no ``edge`` join and no profile-side tally remain.
    assert 'edge ' not in row['query'] and 'tally distinct' not in row['query']
    assert 'if ($state == $observed)' in row['query']
    assert 'where $observed != $next;' in row['query']


# The declared-constant machinery, per language that declares one. Go spells its
# states as a module-level ``const`` block and JavaScript as an object literal, so
# both already keyed identity by name and are covered by the query tests above.
DECLARED_ENUMS = {
    'typescript': {'Idle', 'Running'},
    'java': {'IDLE', 'RUNNING'},
    'csharp': {'Idle', 'Running'},
    'cpp': {'Idle', 'Running'},
    'rust': {'Idle', 'Running'},
}


@pytest.mark.parametrize('language', sorted(DECLARED_ENUMS))
def test_enum_declaration_is_a_nominal_type_carrying_its_constants(language):
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'state.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    enums = [e for e in graph.entities.values() if e.kind == 'CLASS' and e.name == 'State']
    assert len(enums) == 1, [e.id for e in enums]
    constants = [e for e in graph.entities.values()
                 if e.kind == 'MEMBER' and e.id.startswith(enums[0].id + '/MEMBER:')]
    assert {e.name for e in constants} == DECLARED_ENUMS[language]


@pytest.mark.parametrize('language', sorted(DECLARED_ENUMS))
def test_each_constant_has_one_identity_however_often_it_is_referenced(language):
    """Four references collapse to two entities: identity is the declaration.

    ``State::Idle`` appears in the guard and ``State::Running`` in the write, and
    each appears again in the other branch. If identity were per occurrence the
    count would be satisfied by repeating one state, which is the false positive
    this capability exists to close.
    """
    graph = link_project([lower_source(SOURCES[language], language,
                                       f'state.{EXTENSIONS[language]}')])
    enums = [e for e in graph.entities.values() if e.kind == 'CLASS' and e.name == 'State']
    constants = [e for e in graph.entities.values()
                 if e.kind == 'MEMBER' and e.id.startswith(enums[0].id + '/MEMBER:')]
    assert len(constants) == len(DECLARED_ENUMS[language]), [e.id for e in constants]
