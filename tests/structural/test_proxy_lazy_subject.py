"""Proxy ``lazy-subject``: guarded creation of the subject and later delegation.

The variant is a published rule, so the test goes through the registry name
``proxy#lazy-subject``.

The contract does not require a particular spelling of the absence test. What it
requires is that the write is **guarded by the field itself** (``GUARDS_WRITE``),
that the access method constructs **another** type, and that it delegates over
that same field. That is what covers a null comparison, Rust's ``Option`` and a
``flag`` guard being rejected alike.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'proxy#lazy-subject'

SOURCES = {
    'python': ('''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
    def request(self):
        if self.subject is None:
            self.subject = RealSubject()
        return self.subject.request()
''', 'p.py'),
    'javascript': ('''class RealSubject {
  request() { return 1; }
}
class Proxy {
  constructor() { this.subject = null; }
  request() {
    if (this.subject === null) { this.subject = new RealSubject(); }
    return this.subject.request();
  }
}
''', 'p.js'),
    'typescript': ('''class RealSubject {
  request(): number { return 1; }
}
class Proxy {
  subject: RealSubject | null = null;
  request(): number {
    if (this.subject === null) { this.subject = new RealSubject(); }
    return this.subject.request();
  }
}
''', 'p.ts'),
    'java': ('''class RealSubject { int request() { return 1; } }
class Proxy {
  private RealSubject subject = null;
  int request() {
    if (subject == null) { subject = new RealSubject(); }
    return subject.request();
  }
}
''', 'P.java'),
    'csharp': ('''using System;
class RealSubject { public int Request() { return 1; } }
class Proxy {
  private RealSubject subject = null;
  public int Request() {
    if (subject == null) { subject = new RealSubject(); }
    return subject.Request();
  }
}
''', 'P.cs'),
    'cpp': ('''struct RealSubject { int request() { return 1; } };
struct Proxy {
  RealSubject* subject = nullptr;
  int request() {
    if (subject == nullptr) { subject = new RealSubject(); }
    return subject->request();
  }
};
''', 'p.cpp'),
    'go': ('''package proxy

type RealSubject struct{}

func (r *RealSubject) Request() int { return 1 }

type Proxy struct {
	subject *RealSubject
}

func (p *Proxy) Request() int {
	if p.subject == nil {
		p.subject = &RealSubject{}
	}
	return p.subject.Request()
}
''', 'p.go'),
    'rust': ('''pub struct RealSubject { }

impl RealSubject {
    pub fn request(&self) -> i32 { 1 }
}

pub struct Proxy {
    subject: Option<RealSubject>,
}

impl Proxy {
    pub fn new() -> Proxy { Proxy { subject: None } }
    pub fn request(&mut self) -> i32 {
        if self.subject == None {
            self.subject = Some(RealSubject { });
        }
        self.subject.as_ref().unwrap().request()
    }
}
''', 'p.rs'),
}

EAGER = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = RealSubject()
    def request(self):
        return self.subject.request()
'''

UNGUARDED = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
    def request(self):
        self.subject = RealSubject()
        return self.subject.request()
'''

NO_DELEGATION = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
    def request(self):
        if self.subject is None:
            self.subject = RealSubject()
        return 0
'''

OTHER_FIELD_DELEGATED = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
        self.other = RealSubject()
    def request(self):
        if self.subject is None:
            self.subject = RealSubject()
        return self.other.request()
'''

CREATION_NOT_STORED = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
    def request(self):
        if self.subject is None:
            RealSubject()
        return self.subject.request()
'''

GUARD_ON_ANOTHER_FLAG = '''class RealSubject:
    def request(self):
        return 1

class Proxy:
    def __init__(self):
        self.subject = None
    def request(self):
        if flag:
            self.subject = RealSubject()
        return self.subject.request()
'''


def detect(language, source, path):
    graph = link_project([lower_source(source, language, path)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
def test_guarded_creation_and_later_delegation_is_detected(language):
    source, path = SOURCES[language]
    matches = detect(language, source, path)
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    assert bindings['$subject'] != bindings['$created']
    assert bindings['$created'].endswith('/CLASS:RealSubject')


def test_eager_subject_without_a_guard_is_rejected():
    assert not detect('python', EAGER, 'p.py')


def test_unguarded_assignment_is_rejected():
    assert not detect('python', UNGUARDED, 'p.py')


def test_access_without_delegation_is_rejected():
    assert not detect('python', NO_DELEGATION, 'p.py')


def test_delegation_on_another_field_is_rejected():
    assert not detect('python', OTHER_FIELD_DELEGATED, 'p.py')


def test_creation_that_is_not_stored_is_rejected():
    assert not detect('python', CREATION_NOT_STORED, 'p.py')


def test_guard_on_an_unrelated_flag_is_rejected():
    """GUARDS_WRITE requires the guard to reference the guarded field itself."""
    assert not detect('python', GUARD_ON_ANOTHER_FLAG, 'p.py')


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'proxy')
    row = next(v for v in rule.variants if v['id'] == 'lazy-subject')
    assert sorted(row['languages']) == sorted(SOURCES)
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'GUARDS_WRITE' in row['query'] and 'ALLOCATES_TYPE' in row['query']
