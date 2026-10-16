# Actual compact output examples

Captured from a disposable three-file project through CLI and one persistent MCP session. These demonstrate presentation, not a retrieval-quality benchmark. All output is captured verbatim. Path of the temporary fixture: /private/tmp/ken-output-demo-3uq6__4a

## ken_find

Arguments: `{"query": "Reader.read_value", "scope": "symbols"}`

```text
reader.py:6-8 :: Reader.read_value (method)
docstring: Return the stored value for a setting key.
match: exact
preview:
  reader.py:6-8 :: live source preview
  6 |     def read_value(self, key):
  7 |         """Return the stored value for a setting key."""
  8 |         return get_value(key)
tests/test_reader.py:3-4 :: test_read_value (function)
preview:
  tests/test_reader.py:3-4 :: live source preview
  3 | def test_read_value():
  4 |     assert Reader().read_value("color") == "blue"
settings.py:4-6 :: get_value (function)
docstring: Read a stored setting.
preview:
  settings.py:4-6 :: live source preview
  4 | def get_value(key):
  5 |     """Read a stored setting."""
  6 |     return VALUES[key]
reader.py:3-8 :: Reader (class)
docstring: Read stored application settings.
preview:
  reader.py:3-8 :: live source preview
  3 | class Reader:
  4 |     """Read stored application settings."""
  5 |
  6 |     def read_value(self, key):
  7 |         """Return the stored value for a setting key."""
  8 |         return get_value(key)
```

## ken_read

Arguments: `{"path": "reader.py", "include": ["source"], "qualname": "Reader.read_value"}`

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

## ken_related

Arguments: `{"target": "reader.py", "relation": "neighbors"}`

```text
reader.py
imports:
  settings.py:1-1
  module: settings
  internal: true
imported_by:
  tests/test_reader.py:1-1
  language: python
  module: reader
tests:
  tests/test_reader.py
  reason: imports target; named for target
neighbors:
  settings.py
  tests/test_reader.py
```

## ken_rank

Arguments: `{"scope": "project"}`

```text
files: 3
languages:
  python: 3
top_dirs:
  tests
  files: 1
largest_symbol_files:
  reader.py
  symbols: 2
  tests/test_reader.py
  symbols: 1
  settings.py
  symbols: 1
```

## ken_rule

Arguments: `{"action": "list"}`

```text
No results.
```

## ken_check

Arguments: `{}`

```text
run_id: 15ee267b380a4a1d9c11b745b5ec4300
status: not_applicable
scope: project
selection: .
created_at: 2026-10-16T03:50:43.000902+00:00
claim: Selected source contracts only; not proof of runtime behavior or absence of all bugs.
```

## ken_who

Arguments: `{"question": "Who reads stored application settings?"}`

```text
status: candidates
score_kind: heuristic_not_probability
candidates:
  reader.py:3-3 (class)
  symbol: Reader
  evidence: Read stored application settings.
  verification:
    evidence.returned_calls: unknown_candidates=1; reason=usage_inventory_open
  settings.py:4-4 (function)
  symbol: get_value
  evidence: Read a stored setting.
  verification:
    evidence.returned_calls: unknown_candidates=1; reason=usage_inventory_open
  settings.py:1-1 (module)
  evidence: Store and retrieve application settings.
  verification:
    evidence.returned_calls: unknown_candidates=1; reason=usage_inventory_open
verification:
  coverage.usages: unknown_candidates=1; reason=usage_inventory_open
```

## ken_remember

Arguments: `{"topic": "settings-reader", "content": "Reader.read_value delegates lookup to settings.get_value.", "anchor_file": "reader.py"}`

```text
topic: settings-reader
anchors: 1
```

## ken_recall

Arguments: `{"topic": "settings-reader", "detail": "answer"}`

```text
memories:
  topic: settings-reader
  conclusion: Reader.read_value delegates lookup to settings.get_value.
  conclusion_complete: true
  kind: note
  validity:
    state: untracked
  expand:
    topic: settings-reader
    detail: full
  reuse: review_inputs_before_reusing
omitted: 0
detail: answer
validity_scope: Declared inputs only; the conclusion and assumptions are not independently proved.
```

## ken_reason_record

Arguments: `{"source": "demo-doc", "facts": [{"predicate": "reads", "subject": "Reader", "object": "settings"}], "evidence": "reader.py class docstring"}`

```text
changed: true
revision: 1
update: append_delta
```

## ken_reason

Arguments: `{"question": "Who reads settings?", "goal": {"predicate": "reads", "subject": "?answer", "object": "settings"}}`

```text
status: supported
answers:
  fact:
    predicate: reads
    subject: Reader
    object: settings
    negative: false
    scope: present
  binding:
    ?answer: Reader
  premise_sources:
    demo-doc
answers_truncated: false
context: main
revision: 1
world: base
query:
  predicate: reads
  subject: ?answer
  object: settings
  negative: false
  scope: present
semantics: Conditional on supplied premises, interpretations and scope; not verified world truth.
sources:
  demo-doc: reader.py class docstring
answer: Hay apoyo en las premisas para la consulta.
question: Who reads settings?
search:
  pending: 0
  complete: true
  resumable: false
```

## ken_calculate

Arguments: `{"expression": "(1/3 + 1/6) * 6"}`

```text
status: calculated
expression: (1/3 + 1/6) * 6
exact: 3
method: rational-arithmetic/1
stored_as_premise: false
```

## ken search-symbols Reader.read_value --path /private/tmp/ken-output-demo-3uq6__4a

```text
reader.py:6-8 :: Reader.read_value (method)
docstring: Return the stored value for a setting key.
match: exact
preview:
  reader.py:6-8 :: live source preview
  6 |     def read_value(self, key):
  7 |         """Return the stored value for a setting key."""
  8 |         return get_value(key)
tests/test_reader.py:3-4 :: test_read_value (function)
preview:
  tests/test_reader.py:3-4 :: live source preview
  3 | def test_read_value():
  4 |     assert Reader().read_value("color") == "blue"
settings.py:4-6 :: get_value (function)
docstring: Read a stored setting.
preview:
  settings.py:4-6 :: live source preview
  4 | def get_value(key):
  5 |     """Read a stored setting."""
  6 |     return VALUES[key]
reader.py:3-8 :: Reader (class)
docstring: Read stored application settings.
preview:
  reader.py:3-8 :: live source preview
  3 | class Reader:
  4 |     """Read stored application settings."""
  5 |
  6 |     def read_value(self, key):
  7 |         """Return the stored value for a setting key."""
  8 |         return get_value(key)
```

## ken search-files reader --path /private/tmp/ken-output-demo-3uq6__4a

```text
reader.py
language: python
match: exact
reader.py:3-3 :: Reader (class)
reader.py:6-6 :: read_value (method)
preview:
  reader.py:3-8 :: live source preview
  3 | class Reader:
  4 |     """Read stored application settings."""
  5 |
  6 |     def read_value(self, key):
  7 |         """Return the stored value for a setting key."""
  8 |         return get_value(key)
tests/test_reader.py
language: python
match: tokens
tests/test_reader.py:3-3 :: test_read_value (function)
preview:
  tests/test_reader.py:3-4 :: live source preview
  3 | def test_read_value():
  4 |     assert Reader().read_value("color") == "blue"
settings.py
language: python
settings.py:4-4 :: get_value (function)
preview:
  settings.py:4-6 :: live source preview
  4 | def get_value(key):
  5 |     """Read a stored setting."""
  6 |     return VALUES[key]
```

## ken status /private/tmp/ken-output-demo-3uq6__4a

```text
project_root  : /private/tmp/ken-output-demo-3uq6__4a
project_id    : compact-output-demo
db            : /private/tmp/ken-output-demo-3uq6__4a/.ken/ken.db  (4KiB)
files indexed : 3 (3 embedded)
symbols       : 4 (4 embedded)
sessions      : 0 total, 0 active, 0 scored
contexts      : 0 (0 prompts, 0 embedded)
interactions  : 0
findings      : 1 (1 embedded)
doc intents   : 4 (4 embedded)
rank signals  : index=yes, embeddings=ready, predictive=no, findings=yes
embedding cov : 7/7 (100.0%)
recommendation: submit at least one prompt through a hooked agent to seed context history
recommendation: let hooks run through a few real turns to build predictive history
daemon        : stopped
```

## ken kql2 /private/tmp/ken-output-demo-3uq6__4a/readers.kql --root /private/tmp/ken-output-demo-3uq6__4a --cache-mb 0

```text
row 1:
  column_1: Reader
language: kql/2
query: readers
complete: true
coverage_complete: true
unknown_candidates: 0
results_truncated: false
timing:
  total_ms: 45.5
  compile_ms: 11.5
  build_ms: 14.4
  query_ms: 0.2
```

## ken structural search --path /private/tmp/ken-output-demo-3uq6__4a --query method(name: /^read_value$/) as $m; --cache-mb 0

```text
matches:
  reader.py:6-6
  bindings:
    $m: reader.py::module/CLASS:Reader/CALLABLE:read_value@95
  confidence: 1.0
count: 1
complete: true
analysis:
  files: 3
  skipped: 0
  coverage_complete: true
  elapsed_ms: 8.933
note: Structural evidence consistent with an idiom; not proof of intent.
```

## ken tools --path /private/tmp/ken-output-demo-3uq6__4a read reader.py --include source --qualname Reader.read_value

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

## ken tools --path /private/tmp/ken-output-demo-3uq6__4a --json read reader.py --include source --qualname Reader.read_value

```text
{
  "ok": true,
  "path": "reader.py",
  "source": {
    "ok": true,
    "path": "reader.py",
    "snippets": [
      {
        "label": "Reader.read_value",
        "line": 6,
        "line_end": 8,
        "code": "6:     def read_value(self, key):\n7:         \"\"\"Return the stored value for a setting key.\"\"\"\n8:         return get_value(key)"
      }
    ]
  }
}
```
