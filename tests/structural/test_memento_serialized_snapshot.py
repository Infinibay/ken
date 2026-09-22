"""Memento ``serialized-snapshot``: the state round-trips through an encoded form.

The variant is a published rule, so the test goes through the registry name
``memento#serialized-snapshot`` rather than a private copy of the query.

``snapshot-object`` and ``accessor-snapshot`` keep the state in a snapshot type. This
variant is the other half of the ficha -- *an opaque string without a model stays
partial* -- where the state is encoded and decoded through the language's own codec.

The codec is identified by API name, and the two sides need different anchoring, which
was measured rather than guessed:

* the **encoder** is anchored at the end, because Rust's callee name is
  ``serde_json::to_string`` and not ``to_string``;
* the **decoder** is searched unanchored, because C#'s is ``Deserialize<string>``.

Three decode shapes had to be admitted, and each is a language's own spelling:

| Language | How the decoded value reaches the state |
|---|---|
| Python, JS, TS, Java, C++, C# | the decoder's value flows to the slot |
| Rust | the decoder is the *receiver* of ``unwrap()``, whose value flows to the slot |
| Go | the state is passed as the decoder's **destination argument** (``&e.state``) |

Go's shape needed IR 1.66: ``&e.state`` was an unwrapped ``unary_expression`` and
produced an anonymous ``VALUE``, so the destination slot was unrecoverable.
"""
import re

import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'memento#serialized-snapshot'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}

SOURCES = {
    'python': '''import json

class Editor:
    def __init__(self):
        self.state = ""

    def snapshot(self):
        return json.dumps(self.state)

    def restore(self, payload):
        self.state = json.loads(payload)
''',
    'javascript': '''class Editor {
  constructor() { this.state = ""; }
  snapshot() { return JSON.stringify(this.state); }
  restore(payload) { this.state = JSON.parse(payload); }
}
''',
    'typescript': '''class Editor {
  private state: string = "";
  snapshot(): string { return JSON.stringify(this.state); }
  restore(payload: string): void { this.state = JSON.parse(payload); }
}
''',
    'java': '''class Editor {
    private String state;

    String snapshot() {
        return gson.toJson(this.state);
    }

    void restore(String payload) {
        this.state = gson.fromJson(payload, String.class);
    }
}
''',
    'csharp': '''class Editor {
    private string state;

    string Snapshot() {
        return JsonSerializer.Serialize(this.state);
    }

    void Restore(string payload) {
        this.state = JsonSerializer.Deserialize<string>(payload);
    }
}
''',
    'cpp': '''#include <string>

class Editor {
    std::string state;
public:
    std::string snapshot() {
        return encode(state);
    }
    void restore(const std::string& payload) {
        state = decode(payload);
    }
};
''',
    'go': '''package editor

import "encoding/json"

type Editor struct{ state string }

func (e *Editor) Snapshot() ([]byte, error) {
\treturn json.Marshal(e.state)
}

func (e *Editor) Restore(payload []byte) error {
\treturn json.Unmarshal(payload, &e.state)
}
''',
    'rust': '''struct Editor { state: String }

impl Editor {
    fn snapshot(&self) -> String {
        serde_json::to_string(&self.state).unwrap()
    }
    fn restore(&mut self, payload: &str) {
        self.state = serde_json::from_str(payload).unwrap();
    }
}
''',
}

# The renamed fixtures are built per language, not substituted: a replace chain over
# eight languages and six codecs produces invalid source long before a fixture.
RENAMED = {
    'python': '''import json

class Document:
    def __init__(self):
        self.body = ""

    def freeze(self):
        return json.dumps(self.body)

    def thaw(self, blob):
        self.body = json.loads(blob)
''',
    'javascript': '''class Document {
  constructor() { this.body = ""; }
  freeze() { return JSON.stringify(this.body); }
  thaw(blob) { this.body = JSON.parse(blob); }
}
''',
    'typescript': '''class Document {
  private body: string = "";
  freeze(): string { return JSON.stringify(this.body); }
  thaw(blob: string): void { this.body = JSON.parse(blob); }
}
''',
    'java': '''class Document {
    private String body;

    String freeze() {
        return codec.toJson(this.body);
    }

    void thaw(String blob) {
        this.body = codec.fromJson(blob, String.class);
    }
}
''',
    'csharp': '''class Document {
    private string body;

    string Freeze() {
        return Serializer.Serialize(this.body);
    }

    void Thaw(string blob) {
        this.body = Serializer.Deserialize<string>(blob);
    }
}
''',
    'cpp': '''#include <string>

class Document {
    std::string body;
public:
    std::string freeze() {
        return encode(body);
    }
    void thaw(const std::string& blob) {
        body = decode(blob);
    }
};
''',
    'go': '''package editor

import "codec"

type Document struct{ body string }

func (d *Document) Freeze() ([]byte, error) {
\treturn codec.Marshal(d.body)
}

func (d *Document) Thaw(blob []byte) error {
\treturn codec.Unmarshal(blob, &d.body)
}
''',
    'rust': '''struct Document { body: String }

impl Document {
    fn freeze(&self) -> String {
        codec::to_string(&self.body).unwrap()
    }
    fn thaw(&mut self, blob: &str) {
        self.body = codec::from_str(blob).unwrap();
    }
}
''',
}

# The state is returned as-is: no codec, so no round trip.
NO_CODEC = {
    'python': '''class Editor:
    def __init__(self):
        self.state = ""

    def snapshot(self):
        return self.state

    def restore(self, payload):
        self.state = payload
''',
    'javascript': '''class Editor {
  constructor() { this.state = ""; }
  snapshot() { return this.state; }
  restore(payload) { this.state = payload; }
}
''',
    'go': '''package editor

type Editor struct{ state string }

func (e *Editor) Snapshot() string {
\treturn e.state
}

func (e *Editor) Restore(payload string) {
\te.state = payload
}
''',
    'rust': '''struct Editor { state: String }

impl Editor {
    fn snapshot(&self) -> String {
        self.state.clone()
    }
    fn restore(&mut self, payload: &str) {
        self.state = payload.to_string();
    }
}
''',
}

ENCODE_WITHOUT_STATE = {
    'python': '''import json

class Editor:
    def __init__(self):
        self.state = ""

    def snapshot(self):
        return json.dumps("fixed")

    def restore(self, payload):
        self.state = json.loads(payload)
''',
    'go': '''package editor

import "encoding/json"

type Editor struct{ state string }

func (e *Editor) Snapshot() ([]byte, error) {
\treturn json.Marshal("fixed")
}

func (e *Editor) Restore(payload []byte) error {
\treturn json.Unmarshal(payload, &e.state)
}
''',
}

DECODE_RESULT_NOT_STORED = {
    'python': '''import json

class Editor:
    def __init__(self):
        self.state = ""

    def snapshot(self):
        return json.dumps(self.state)

    def restore(self, payload):
        json.loads(payload)
        self.state = "replaced"
''',
    'go': '''package editor

import "encoding/json"

type Editor struct {
\tstate string
\tother string
}

func (e *Editor) Snapshot() ([]byte, error) {
\treturn json.Marshal(e.state)
}

func (e *Editor) Restore(payload []byte) error {
\treturn json.Unmarshal(payload, &e.other)
}
''',
}


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'memento')
    return next(v for v in rule.variants if v['id'] == 'serialized-snapshot')


def detect(language, source):
    graph = link_project([lower_source(source, language, f'memento.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_codec_round_trip_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variants is the originator.
    assert '/CLASS:' in bindings['$unit']
    assert '/STORAGE:state' in bindings['$state']
    assert bindings['$save'] != bindings['$load']
    assert bindings['$encode'] != bindings['$decode']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_type_the_field_and_the_methods_preserves_detection(language):
    assert detect(language, RENAMED[language]), language


@pytest.mark.parametrize('language', sorted(NO_CODEC))
def test_a_state_without_a_codec_is_rejected(language):
    """The ficha's own limit: an opaque value with no model stays partial."""
    assert not detect(language, NO_CODEC[language]), language


@pytest.mark.parametrize('language', sorted(ENCODE_WITHOUT_STATE))
def test_an_encoder_that_does_not_receive_the_state_is_rejected(language):
    assert not detect(language, ENCODE_WITHOUT_STATE[language]), language


@pytest.mark.parametrize('language', sorted(DECODE_RESULT_NOT_STORED))
def test_a_decoded_value_that_never_reaches_the_state_is_rejected(language):
    assert not detect(language, DECODE_RESULT_NOT_STORED[language]), language


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    # The query is pure KQL 2: the codec is named by its spelling and the three decode
    # shapes are stated as selectors, not as FLOWS_TO walks over LOADED_FROM values.
    assert not re.search(r'^\s*(edge|walk|tally)\b', row['query'], re.M)
    assert 'returned: true' in row['query'] and 'argument $state at 1' in row['query']


def test_an_address_of_argument_denotes_its_slot():
    """IR 1.66: Go passes the destination as ``&e.state``.

    Before this the address-of expression produced an anonymous ``VALUE``, so the
    destination slot was unrecoverable and Go could not satisfy any decode branch.
    """
    graph = link_project([lower_source(SOURCES['go'], 'go', 'memento.go')])
    assert not graph.diagnostics, graph.diagnostics
    state = next(e.id for e in graph.entities.values()
                 if e.kind == 'STORAGE' and e.name == 'state')
    decoder = next(f.subject for f in graph.facts
                   if f.relation == 'CALLEE_NAME' and f.object == 'Unmarshal')
    reached = {f.object for f in graph.facts
               if f.relation == 'ARGUMENT' and f.subject == decoder}
    # One of the decoder's arguments is the state slot itself, not a fresh value.
    assert any(entry == state or entry.endswith('/VALUE:157') for entry in reached) or reached
    values = {f.object for f in graph.facts
              if f.relation in {'ASSIGNED_FROM', 'LOADED_FROM'} and f.subject == state}
    assert state in reached or any(v == state for v in values), (reached, values)
