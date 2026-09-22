"""Flyweight ``entry-api``: the map's own get-or-add retains the object.

The variant is a published rule, so the test goes through the registry name
``flyweight#entry-api`` rather than a private copy of the query.

``explicit-interning`` covers the hand-written pool: look up, miss, construct, insert,
return -- all in the analysed method. This variant is the other half of the ficha: the
**map's own entry API** does the retaining, so the method never writes the pool
itself. That is why the pool field's *receiver* role is the substance here: the entry
call has to be made on the field, not on a local or a parameter that happens to hold a
map.

The four languages spell the API differently and the difference is not cosmetic:

| Language | Entry call | Shape of the retained value |
|---|---|---|
| Java | ``entries.computeIfAbsent(key, k -> new Value(k))`` | the call itself |
| C# | ``entries.GetOrAdd(key, k => new Value(k))`` | the call itself |
| C++ | ``entries.try_emplace(key, key).first->second`` | a member chain rooted at the call |
| Rust | ``self.entries.entry(key).or_insert_with(\\|\\| Value::new())`` | the wrapper whose receiver is the call |

The contract accepts all three shapes and ``query_claim`` says the factory is not
required to run exactly once, because none of these APIs promises that to a reader of
the source.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.kenql import query_graph
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'flyweight#entry-api'
LANGUAGES = ['java', 'csharp', 'cpp', 'rust']
EXTENSIONS = {'java': 'java', 'csharp': 'cs', 'cpp': 'cpp', 'rust': 'rs'}

SOURCES = {
    'java': '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(String key) {
        return entries.computeIfAbsent(key, k -> new Value(k));
    }
}
''',
    'csharp': '''using System.Collections.Concurrent;

class Cache {
    private ConcurrentDictionary<string, Value> entries;

    Value Lookup(string key) {
        return entries.GetOrAdd(key, k => new Value(k));
    }
}
''',
    'cpp': '''#include <map>
#include <string>

class Cache {
    std::map<std::string, Value> entries;
public:
    Value& lookup(const std::string& key) {
        return entries.try_emplace(key, key).first->second;
    }
};
''',
    'rust': '''use std::collections::HashMap;

struct Cache { entries: HashMap<String, Value> }

impl Cache {
    fn lookup(&mut self, key: String) -> &Value {
        self.entries.entry(key).or_insert_with(|| Value::new())
    }
}
''',
}

JAVA_PLAIN_GET = '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(String key) {
        return entries.get(key);
    }
}
'''

JAVA_CONSTANT_KEY = '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(String key) {
        return entries.computeIfAbsent("fixed", k -> new Value(k));
    }
}
'''

JAVA_LOCAL_MAP = '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(String key) {
        Map<String, Value> local = new HashMap<>();
        return local.computeIfAbsent(key, k -> new Value(k));
    }
}
'''

JAVA_PARAMETER_MAP = '''import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(Map<String, Value> incoming, String key) {
        return incoming.computeIfAbsent(key, k -> new Value(k));
    }
}
'''

JAVA_NO_KEY = '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup() {
        return entries.computeIfAbsent("fixed", k -> new Value(k));
    }
}
'''

JAVA_NOT_RETAINED = '''import java.util.HashMap;
import java.util.Map;

class Cache {
    private Map<String, Value> entries;

    Value lookup(String key) {
        entries.computeIfAbsent(key, k -> new Value(k));
        return new Value(key);
    }
}
'''

CPP_LOCAL_MAP = '''#include <map>
#include <string>

class Cache {
    std::map<std::string, Value> entries;
public:
    Value lookup(const std::string& key) {
        std::map<std::string, Value> local;
        return local.try_emplace(key, key).first->second;
    }
};
'''

CPP_PLAIN_GET = '''#include <map>
#include <string>

class Cache {
    std::map<std::string, Value> entries;
public:
    Value lookup(const std::string& key) {
        return entries.at(key);
    }
};
'''

RUST_NO_ENTRY = '''use std::collections::HashMap;

struct Cache { entries: HashMap<String, Value> }

impl Cache {
    fn lookup(&self, key: String) -> Option<&Value> {
        self.entries.get(&key)
    }
}
'''

RUST_PARAMETER_MAP = '''use std::collections::HashMap;

struct Cache { entries: HashMap<String, Value> }

impl Cache {
    fn lookup(incoming: HashMap<String, Value>, key: String) -> Value {
        incoming.entry(key).or_insert_with(|| Value::new()).clone()
    }
}
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'flyweight')
    return next(v for v in rule.variants if v['id'] == 'entry-api')


def detect(language, source):
    graph = link_project([lower_source(source, language, f'flyweight.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_entry_api_on_the_pool_field_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variant is the class holding the pool.
    assert '/CLASS:Cache' in bindings['$unit']
    assert '/STORAGE:entries' in bindings['$pool']
    assert bindings['$lookup'] != bindings['$pool']
    assert bindings['$entry'].startswith(('java.', 'cs.', 'cpp.', 'rs.', 'a.', 'flyweight.'))


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_type_and_method_preserves_detection(language):
    renamed = SOURCES[language].replace('Cache', 'Registry').replace('lookup', 'acquire').replace('Lookup', 'Acquire')
    assert detect(language, renamed), language


def test_a_plain_lookup_without_the_entry_api_is_rejected():
    assert not detect('java', JAVA_PLAIN_GET)
    assert not detect('cpp', CPP_PLAIN_GET)
    assert not detect('rust', RUST_NO_ENTRY)


def test_a_constant_key_is_rejected():
    assert not detect('java', JAVA_CONSTANT_KEY)


def test_the_entry_api_must_be_called_on_the_field_not_on_a_local():
    assert not detect('java', JAVA_LOCAL_MAP)
    assert not detect('cpp', CPP_LOCAL_MAP)


def test_the_entry_api_must_be_called_on_the_field_not_on_a_parameter():
    assert not detect('java', JAVA_PARAMETER_MAP)
    assert not detect('rust', RUST_PARAMETER_MAP)


def test_the_method_must_take_a_key_parameter():
    assert not detect('java', JAVA_NO_KEY)


def test_the_method_must_yield_the_retained_object():
    """Calling the entry API is not enough; the retained object has to come back."""
    assert not detect('java', JAVA_NOT_RETAINED)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'receiver: $pool' in row['query'] and 'or_insert_with' in row['query']
    assert 'exactly-once' in row['query_claim']


def test_the_argument_position_lives_on_the_occurrence_not_on_the_relation():
    """``ARGUMENT`` in the query view carries no attributes.

    The call's argument position is recorded on the ``ENTITY ARGUMENT`` fact of the
    synthetic occurrence node, so a query must filter there:
    ``require $argument ENTITY ARGUMENT [position: 0]``. Filtering on the ``ARGUMENT``
    fact itself matches nothing and looks like an absent pattern.
    """
    graph = link_project([lower_source(SOURCES['java'], 'java', 'flyweight.java')])
    view = query_graph(graph).ir
    bare = [f for f in view.facts if f.relation == 'ARGUMENT']
    assert bare, 'the fixture must pass arguments'
    assert all(not f.attrs for f in bare), [f.attrs for f in bare]
    occurrences = [f for f in view.facts if f.relation == 'ENTITY' and f.object == 'ARGUMENT']
    assert occurrences, 'argument occurrences must be classified'
    assert all('position' in f.attrs for f in occurrences)
