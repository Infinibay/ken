"""What an insertion *carries*: the local alias and the one-argument wrapper.

A language that binds the value to a local name before enqueuing it, or wraps it in
a one-argument constructor, still enqueues that value, so ``insert $value into
$queue`` resolves the operand through ``ASSIGNED_FROM``, ``ARGUMENT`` and
``FLOWS_TO`` instead of only reading the node stored verbatim.
"""
from __future__ import annotations

from ken.kql2.service import search

QUEUED = ('language "kql/2"; module t; query q { '
          'callable $action { constructor: false; } '
          'type $unit { field $pending { name: "pending"; } method $submit { param $payload { } '
          'body { insert $action into $pending; } } } select $unit; }')


def test_insert_follows_a_local_alias_to_the_value_it_binds(tmp_path):
    (tmp_path / 'a.js').write_text(
        'class Dispatcher {\n'
        '  constructor() { this.pending = []; }\n'
        '  submit(payload) {\n'
        '    const action = (context) => payload + context;\n'
        '    this.pending.push(action);\n'
        '  }\n'
        '}\n')
    result = search(tmp_path, QUEUED, cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_insert_follows_a_one_argument_wrapper(tmp_path):
    """``queue.push(Box::new(action))`` enqueues the closure the wrapper carries."""
    (tmp_path / 'a.rs').write_text(
        'pub struct Dispatcher { pending: Vec<Box<dyn Fn(i32) -> i32>> }\n'
        'impl Dispatcher {\n'
        '    pub fn submit(&mut self, payload: i32) {\n'
        '        let action = move |context: i32| payload + context;\n'
        '        self.pending.push(Box::new(action));\n'
        '    }\n'
        '}\n')
    result = search(tmp_path, QUEUED, cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_insert_rejects_a_value_that_carries_no_callable(tmp_path):
    (tmp_path / 'a.js').write_text(
        'class Dispatcher {\n'
        '  constructor() { this.pending = []; }\n'
        '  submit(payload) {\n'
        '    const value = payload + 1;\n'
        '    this.pending.push(value);\n'
        '  }\n'
        '}\n')
    result = search(tmp_path, QUEUED, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result
