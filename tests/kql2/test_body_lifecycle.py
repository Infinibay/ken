"""Lifecycle guards a walk and an insertion carry in BODY.

``iterate``/``insert``/``call on`` name *evidence*, not just a shape: the walk must enter
with that collection (the IR says so by publishing ``ITERATION_ENTRY_SOURCE``), the loop
must be the walk that invokes the element, and an insertion names the caller's input only
while that input is still unwritten. ``tests/structural/test_queued_commands.py`` and
``tests/structural/test_modern_catalog_precision.py`` pin the catalogue side; this is the
primitives' own contract.
"""
from __future__ import annotations

from ken.kql2.service import search


def write(tmp_path, source: str) -> None:
    (tmp_path / 'a.py').write_text(source)


INSERT = ('language "kql/2"; module t; query q { '
          'type $unit { field $listeners {} method $subscribe { param $listener {} '
          'body { insert $listener into $listeners; } } } select $unit; }')

WALK = ('language "kql/2"; module t; query q { '
        'type $unit { field $tasks {} method $consume { constructor: false; '
        'body { iterate $tasks as $item as $loop { '
        'body { call on $item { } as $call; } } } } } select $unit; }')


def test_insert_matches_while_the_input_is_unwritten(tmp_path):
    write(tmp_path, 'class Subject:\n'
                    '    def __init__(self): self.listeners = []\n'
                    '    def subscribe(self, listener):\n'
                    '        self.listeners.append(listener)\n')
    result = search(tmp_path, INSERT, cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_insert_rejects_a_rebound_input(tmp_path):
    write(tmp_path, 'class Subject:\n'
                    '    def __init__(self): self.listeners = []\n'
                    '    def subscribe(self, listener):\n'
                    '        listener = None\n'
                    '        self.listeners.append(listener)\n')
    # The collection receives the rebound local, not the caller's input.
    result = search(tmp_path, INSERT, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_walk_matches_while_it_enters_with_the_collection(tmp_path):
    write(tmp_path, 'class Queue:\n'
                    '    def __init__(self): self.tasks = []\n'
                    '    def consume(self):\n'
                    '        for item in self.tasks:\n'
                    '            item.run()\n')
    result = search(tmp_path, WALK, cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_walk_rejects_a_collection_emptied_before_it(tmp_path):
    write(tmp_path, 'class Queue:\n'
                    '    def __init__(self): self.tasks = []\n'
                    '    def consume(self):\n'
                    '        self.tasks = []\n'
                    '        for item in self.tasks:\n'
                    '            item.run()\n')
    # ``ITERATION_SOURCE`` still names ``tasks``; the walk no longer *enters* with it.
    result = search(tmp_path, WALK, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_walk_rejects_an_element_rebound_before_the_call(tmp_path):
    write(tmp_path, 'class Queue:\n'
                    '    def __init__(self): self.tasks = []\n'
                    '    def consume(self):\n'
                    '        for item in self.tasks:\n'
                    '            item = None\n'
                    '            item.run()\n')
    # The receiver is still spelled ``item``, but the loop no longer invokes the element.
    result = search(tmp_path, WALK, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_walk_matches_across_an_awaited_invocation(tmp_path):
    write(tmp_path, 'class Queue:\n'
                    '    def __init__(self): self.tasks = []\n'
                    '    async def consume(self):\n'
                    '        for item in self.tasks:\n'
                    '            await item.run()\n')
    # ``await`` makes the body's CFG partial; the statement walk stays reliable.
    result = search(tmp_path, WALK, cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result
