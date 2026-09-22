"""``call $c { name: /regex/ }`` — a callee spelling the source qualified.

The published spelling is what the source wrote, not what the pattern hopes for:
Rust's codec is ``serde_json::to_string`` (a path, so a literal list can never claim it
without enumerating imports) and C#'s is ``Deserialize<string>`` (parameterised, so the
name is not the identifier either). A regular expression states the segment that carries
the meaning, exactly as a graph-level ``edge`` matcher always could. The limits are the
graph matcher's: no backreferences and no lookaround, so the two spellings stay regular.
"""
import pytest

from ken.kql2.syntax import ParseError
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

RUST = '''struct Editor { state: String }

impl Editor {
    fn snapshot(&self) -> String {
        serde_json::to_string(&self.state)
    }
}
'''

CSHARP = '''class Editor {
    private string state;

    string Snapshot() {
        return JsonSerializer.Serialize(this.state);
    }

    void Restore(string payload) {
        this.state = JsonSerializer.Deserialize<string>(payload);
    }
}
'''

QUERY = '''language "kql/2";
module ken.probe;

pattern detect(out TypeDecl $unit, out Call $call) {
  type $unit {
    method $m {
      constructor: false;
      body {
        call $call { name: %s; resolution: unresolved; };
      }
    }
  }
}

query results {
  use detect(unit: $unit, call: $call);
  select $unit, $call;
}
'''


def matches(pattern, source=RUST, language='rust', filename='f.rs'):
    graph = link_project([lower_source(source, language, filename)])
    query = QUERY % pattern
    rule = SavedRule(id='probe', name='probe', query=query, source=query, query_language='kql/2')
    return execute_rules(graph, [rule], evidence_mode='strict')['matches']


def test_a_regex_claims_a_qualified_callee_spelling():
    assert matches('/to_string$/')
    assert not matches('/from_str$/')
    # The published spelling is the qualified path, so the anchored bare name is not it.
    assert not matches('/^to_string$/')


def test_a_regex_claims_a_parameterised_callee_spelling():
    assert matches('/Deserialize/', CSHARP, 'csharp', 'f.cs')
    assert not matches('/^Deserialize$/', CSHARP, 'csharp', 'f.cs')
    assert not matches('/Serialize\\(/', CSHARP, 'csharp', 'f.cs')


def test_the_regex_reads_the_qualified_spelling_the_frontend_published():
    # The published spelling writes Rust's path separator, so a pattern that brackets the
    # segment with a literal dot is not the same claim as the one that ends where it does.
    assert not matches('/json\\.to_string$/')
    assert matches('/serde_json::to_string$/')


def test_the_graph_matcher_limits_hold_for_the_name_regex():
    # Lookaround and backreferences are refused where every other KQL 2 regex is refused,
    # so the `name` inventory cannot smuggle a non-regular pattern into the matcher.
    with pytest.raises(ParseError):
        matches('/(?=to_string)/')
    with pytest.raises(ParseError):
        matches('/(to)_\\1/')
