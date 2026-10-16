# Actual compact output examples

Real CLI and MCP captures from disposable Python sources. Code is quoted with its physical line numbers; `[partial]` means only selected source is shown. JSON and full diagnostics remain explicit options. These examples measure presentation, not retrieval accuracy or latency. Blank numbered lines omit trailing whitespace in Markdown; captures.json retains the exact responses.

## ken_find

Arguments: `{"query": "Reader.read_value", "scope": "symbols"}`

```text
reader.py:6-8 :: Reader.read_value
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
  settings.py
imported_by:
  tests/test_reader.py
tests:
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
run_id: 452c97770893471493504f3c6acb76df
status: not_applicable
```

## ken_who

Arguments: `{"question": "Who reads stored application settings?"}`

```text
Candidates:

reader.py:3-8 :: Reader (class)
3 | class Reader:
4 |     """Read stored application settings."""
5 |
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)

settings.py:4-6 :: get_value
4 | def get_value(key):
5 |     """Read a stored setting."""
6 |     return VALUES[key]

settings.py:1-3 (module)
1 | """Store and retrieve application settings."""
2 | VALUES = {"color": "blue"}
3 |
Also shown above: settings.py:4-6.

Verification: reason=Source changed or structural acquisition incomplete.
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
  validity:
    state: untracked
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
semantics: Conditional on supplied premises, interpretations and scope; not verified world truth.
sources:
  demo-doc: reader.py class docstring
answer: Hay apoyo en las premisas para la consulta.
search:
  complete: true
```

## ken_calculate

Arguments: `{"expression": "(1/3 + 1/6) * 6"}`

```text
(1/3 + 1/6) * 6 = 3
```

## ken search-symbols Reader.read_value --path /private/tmp/ken-useful-output-demo-v178-8bd4uosb

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

## ken search-files reader --path /private/tmp/ken-useful-output-demo-v178-8bd4uosb

```text
reader.py:1-2 (file) [partial]
1 | from settings import get_value
2 |
@8-8
8 |         return get_value(key)
@3-5
3 | class Reader:
4 |     """Read stored application settings."""
5 |
```

## ken status /private/tmp/ken-useful-output-demo-v178-8bd4uosb

```text
project_root  : /private/tmp/ken-useful-output-demo-v178-8bd4uosb
files indexed : 3 (0 embedded)
symbols       : 4 (0 embedded)
embedding cov : 0/7 (0.0%)
recommendation: run `ken rank "your task"` once to lazily build embeddings
daemon        : stopped
```

## ken kql2 /private/tmp/ken-useful-output-demo-v178-8bd4uosb/readers.kql --root /private/tmp/ken-useful-output-demo-v178-8bd4uosb --cache-mb 0

```text
row 1:
  column_1: Reader
language: kql/2
query: readers
complete: true
coverage_complete: true
unknown_candidates: 0
results_truncated: false
```

## ken structural search --path /private/tmp/ken-useful-output-demo-v178-8bd4uosb --query 'method(name: /^read_value$/) as $m;' --cache-mb 0

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
note: Structural evidence consistent with an idiom; not proof of intent.
```

## ken tools --path /private/tmp/ken-useful-output-demo-v178-8bd4uosb read reader.py --include source --qualname Reader.read_value

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

## ken tools --path /private/tmp/ken-useful-output-demo-v178-8bd4uosb --json read reader.py --include source --qualname Reader.read_value

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

## ken_find

Arguments: `{"query": "Locate the definition of reader::Reader.read_value.", "scope": "symbols"}`

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

## ken_who

Arguments: `{"question": "Who reads stored application settings?", "path": "large_reader.py"}`

```text
Candidates:

large_reader.py:1-2 :: SettingReader (class) [partial]
1 | class SettingReader:
2 |     """Read stored application settings.
@69-70
69 |     def read_setting(self, key):
70 |         return settings.get_value(key)

Verification: reason=Source changed or structural acquisition incomplete.
```
