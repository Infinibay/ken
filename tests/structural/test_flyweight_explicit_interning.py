"""Flyweight ``explicit-interning``: the method writes and returns the pool itself.

The published variant, exercised through the registry name. The canonical
examples derive the key before touching the pool --::

    key = self.get_key(state)      # python
    const key = this.getKey(state) # typescript
    String key = ...               # java

so the index of the write and of the return is a *local*, not the parameter the
method received. The variant accepts either spelling and keeps them correlated:
the derivation must reach the key parameter, which is what rejects
``self.pool[0] = Glyph(key)`` and ``return self.pool[0]``.
"""
from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = "flyweight#explicit-interning"
LANGUAGES = ["python", "java", "typescript"]
EXTENSIONS = {"python": "py", "java": "java", "typescript": "ts"}

# The key parameter flows into a local, and the pool is indexed by that local.
DERIVED = {
    "python": '''class Glyph:
    def __init__(self, font): self.font = font
    def draw(self, x): return self.font + x

class Pool:
    def __init__(self): self.pool = {}
    def key_for(self, state): return "_".join(sorted(state))
    def get(self, state):
        key = self.key_for(state)
        if not self.pool.get(key):
            self.pool[key] = Glyph(state)
        return self.pool[key]
''',
    "typescript": '''class Glyph {
    private font: string;
    constructor(font: string) { this.font = font; }
    draw(x: number): string { return this.font + x; }
}

class Pool {
    private pool: {[key: string]: Glyph} = {};
    private keyFor(state: string[]): string { return state.join("_"); }
    public get(state: string[]): Glyph {
        const key = this.keyFor(state);
        if (!this.pool[key]) {
            this.pool[key] = new Glyph(state);
        }
        return this.pool[key];
    }
}
''',
    "java": '''class Glyph {
    int font;
    Glyph(int font) { this.font = font; }
    int draw(int x) { return this.font + x; }
}

class Pool {
    Glyph[] pool = new Glyph[100];

    int keyFor(int state) { return state; }

    Glyph get(int state) {
        int key = this.keyFor(state);
        if (this.pool[key] == null) {
            this.pool[key] = new Glyph(state);
        }
        return this.pool[key];
    }
}
''',
}

# A local the method received, but not derived from the key parameter.
FOREIGN_LOCAL = '''class Pool:
    def __init__(self): self.pool = {}
    def get(self, state):
        key = "fixed"
        if not self.pool.get(key):
            self.pool[key] = Glyph(state)
        return self.pool[key]
'''

# The stored object ignores the key parameter.
ABANDONED = '''class Pool:
    def __init__(self): self.pool = {}
    def key_for(self, state): return state
    def get(self, state):
        key = self.key_for(state)
        unused = Glyph(state)
        if not self.pool.get(key):
            self.pool[key] = Glyph("constant")
        return self.pool[key]
'''

CONSTANT_RETURN = '''class Pool:
    def __init__(self): self.pool = {}
    def key_for(self, state): return state
    def get(self, state):
        key = self.key_for(state)
        if not self.pool.get(key):
            self.pool[key] = Glyph(state)
        return self.pool["fixed"]
'''


def detect(language, source):
    graph = link_project([lower_source(source, language, f"pool.{EXTENSIONS[language]}")])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry, evidence_mode="strict")
    assert result["complete"], result["outcomes"]
    return result["matches"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_key_derived_from_the_parameter_still_interns(language):
    matches = detect(language, DERIVED[language])
    assert len(matches) == 1, language
    assert "/CLASS:Pool" in matches[0]["bindings"]["$unit"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_renaming_the_pool_and_the_method_preserves_detection(language):
    renamed = DERIVED[language].replace("Pool", "Registry").replace("keyFor", "hashOf").replace("key_for", "hash_of")
    assert detect(language, renamed), language


def test_a_key_not_derived_from_the_parameter_is_rejected():
    assert not detect("python", FOREIGN_LOCAL)


def test_a_stored_object_that_ignores_the_key_is_rejected():
    assert not detect("python", ABANDONED)


def test_a_return_index_that_is_not_the_key_is_rejected():
    assert not detect("python", CONSTANT_RETURN)
