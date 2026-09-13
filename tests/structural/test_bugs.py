from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.effects import detect_bugs

CASES = [
 ("mutable-default-argument", "python", "def f(values=[]): return values", "def f(values=None): return values"),
 ("bare-except", "python", "try:\n f()\nexcept:\n report()", "try:\n f()\nexcept ValueError:\n report()"),
 ("swallowed-exception", "python", "try:\n f()\nexcept ValueError:\n pass", "try:\n f()\nexcept ValueError:\n raise"),
 ("return-in-finally", "python", "def f():\n try:\n  return 1\n finally:\n  return 2", "def f():\n try:\n  return 1\n finally:\n  cleanup()"),
 ("unreachable-statement", "python", "def f():\n return 1\n work()", "def f(x):\n if x:\n  return 1\n work()"),
 ("self-assignment", "python", "def f(x):\n x = x", "def f(x):\n y = x"),
 ("nan-equality", "javascript", "function f(x) { return x === NaN; }", "function f(x) { return Number.isNaN(x); }"),
 ("tuple-assertion", "python", "def f(x):\n assert (x, 'error')", "def f(x):\n assert x, 'error'"),
 ("swallowed-exception", "javascript", "try { work(); } catch (e) {}", "try { work(); } catch (e) { throw e; }"),
 ("swallowed-exception", "java", "class C { void f() { try { work(); } catch (Exception e) {} } }", "class C { void f() { try { work(); } catch (Exception e) { throw e; } } }"),
 ("unreachable-statement", "csharp", "class C { int F() { return 1; Run(); } }", "class C { int F() { Run(); return 1; } }"),
 ("unreachable-statement", "cpp", "int f() { return 1; work(); }", "int f() { work(); return 1; }"),
]


@pytest.mark.parametrize("rule,language,bad,good", CASES)
@pytest.mark.parametrize("positive", [True, False])
def test_bug_signature_and_close_negative(rule, language, bad, good, positive):
    graph = link_project([lower_source(bad if positive else good, language, "example")])
    assert not graph.diagnostics
    matches = [m for m in detect_bugs(graph) if m["id"] == rule]
    assert bool(matches) is positive
    assert all(m["evidence"] for m in matches)


def test_two_bugs_in_same_function_are_separate_locations():
    graph = link_project([lower_source('def f(x):\n x = x\n x = x\n',"python","a.py")])
    matches = [m for m in detect_bugs(graph) if m["id"] == "self-assignment"]
    assert len(matches) == 2
    assert matches[0]["evidence"] != matches[1]["evidence"]
