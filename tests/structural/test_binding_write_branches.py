"""Branch-aware unique-write gating: only emit UNIQUE_BINDING_WRITE when the
write lives in the callable body proper, not inside a conditional arm."""
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


PYTHON = 'python'


def graph(code, language=PYTHON):
    g = link_project([lower_source(code, language, 'sample')])
    assert not g.diagnostics, g.diagnostics
    return g


def unique_writes(g):
    return {f.object for f in g.facts if f.relation == 'UNIQUE_BINDING_WRITE'}


def value_storage_ids(g):
    return {e.id for e in g.entities.values() if e.kind == 'STORAGE' and e.name == 'value'}


def test_linear_unique_write_in_body_is_marked():
    code = (
        'class Reader:\n def read(self, key): return key\n'
        'class Writer:\n def write(self, value): return value\n'
        'class Surface:\n'
        ' def __init__(self, reader, writer):\n'
        '  self.reader = reader\n  self.writer = writer\n'
        ' def execute(self, key):\n'
        '  value = self.reader.read(key)\n'
        '  return self.writer.write(value)\n'
    )
    g = graph(code)
    value_ids = value_storage_ids(g)
    assert value_ids, 'expected at least one STORAGE named value'
    assert value_ids & unique_writes(g), (
        'expected UNIQUE_BINDING_WRITE for the linear body write of `value`'
    )


def test_single_arm_conditional_write_is_not_marked_unique():
    # Only one arm defines `value`; the other arm leaves it undefined.
    # Per P1.4 the load does not have a unique reaching definition, so
    # the upgrade signal must not be emitted.
    code = (
        'class Reader:\n def read(self, key): return key\n'
        'class Writer:\n def write(self, value): return value\n'
        'class Surface:\n'
        ' def __init__(self, reader, writer):\n'
        '  self.reader = reader\n  self.writer = writer\n'
        ' def execute(self, key, flag):\n'
        '  if flag:\n   value = self.reader.read(key)\n'
        '  return self.writer.write(0)\n'
    )
    g = graph(code)
    value_ids = value_storage_ids(g)
    assert value_ids, 'expected at least one STORAGE named value'
    assert not (value_ids & unique_writes(g)), (
        'single-arm conditional writes must not emit UNIQUE_BINDING_WRITE for `value`: '
        f'{sorted(value_ids & unique_writes(g))}'
    )


def test_two_arm_conditional_writes_are_not_marked_unique():
    code = (
        'class Reader:\n def read(self, key): return key\n'
        'class Writer:\n def write(self, value): return value\n'
        'class Surface:\n'
        ' def __init__(self, reader, writer):\n'
        '  self.reader = reader\n  self.writer = writer\n'
        ' def execute(self, key, flag):\n'
        '  if flag:\n   value = self.reader.read(key)\n'
        '  else:\n   value = self.reader.read(key)\n'
        '  return self.writer.write(value)\n'
    )
    g = graph(code)
    value_ids = value_storage_ids(g)
    assert value_ids, 'expected at least one STORAGE named value'
    assert not (value_ids & unique_writes(g)), (
        'two-arm same-spelling writes must not collapse into one origin for `value`: '
        f'{sorted(value_ids & unique_writes(g))}'
    )


def test_body_write_followed_by_arm_overwrite_is_not_marked_unique():
    code = (
        'class Reader:\n def read(self, key): return key\n'
        'class Writer:\n def write(self, value): return value\n'
        'class Surface:\n'
        ' def __init__(self, reader, writer):\n'
        '  self.reader = reader\n  self.writer = writer\n'
        ' def execute(self, key, flag):\n'
        '  value = self.reader.read(key)\n'
        '  if flag:\n   value = 0\n'
        '  return self.writer.write(value)\n'
    )
    g = graph(code)
    value_ids = value_storage_ids(g)
    assert value_ids, 'expected at least one STORAGE named value'
    assert not (value_ids & unique_writes(g)), (
        'an arm that overwrites the body write must keep VALUE_FLOW may for `value`: '
        f'{sorted(value_ids & unique_writes(g))}'
    )