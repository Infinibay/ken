"""``insert $value into $collection [at $key];`` — a collection effect in BODY.

The effect names what lands in the collection, not just that the collection changed:
the inserted value must be the source operand of that occurrence. ``tests/structural/
test_negative_corpus.py`` and the observer matrix pin the catalogue side; this is the
primitive's own contract.
"""
from __future__ import annotations

from ken.kql2.service import search


def query(body: str, collection: str = 'field $listeners { }') -> str:
    return ('language "kql/2"; module t; query q { '
            f'type $unit {{ {collection} method $subscribe {{ param $listener {{ }} '
            f'body {{ {body} }} }} }} select $unit; }}')


def write(tmp_path, source: str = None) -> None:
    (tmp_path / 'a.py').write_text(source or (
        'class Subject:\n'
        '    def __init__(self): self.listeners = []\n'
        '    def subscribe(self, listener): self.listeners.append(listener)\n'))


def test_insert_matches_the_inserted_parameter(tmp_path):
    write(tmp_path)
    result = search(tmp_path, query('insert $listener into $listeners;'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_insert_rejects_a_value_the_occurrence_does_not_carry(tmp_path):
    write(tmp_path, 'class Subject:\n'
                    '    def __init__(self, other): self.listeners = []; self.other = other\n'
                    '    def subscribe(self, listener): self.listeners.append(self.other)\n')
    # The collection receives ``self.other``, never the parameter.
    result = search(tmp_path, query('insert $listener into $listeners;'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_insert_rejects_another_collection(tmp_path):
    write(tmp_path, 'class Subject:\n'
                    '    def __init__(self): self.listeners = []; self.audit = []\n'
                    '    def subscribe(self, listener): self.audit.append(listener)\n')
    # A role name is a label, not a filter: the pattern says which field it means.
    named = query('insert $listener into $listeners;', 'field $listeners { name: "listeners"; }')
    result = search(tmp_path, named, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_insert_at_key_correlates_the_map_key(tmp_path):
    write(tmp_path, 'class Registry:\n'
                    '    def __init__(self): self.handlers = {}\n'
                    '    def subscribe(self, topic, handler): self.handlers[topic] = handler\n')
    def keyed(key: str) -> str:
        return ('language "kql/2"; module t; query q { '
                'type $unit { field $handlers { name: "handlers"; } method $subscribe { '
                f'param $topic {{ }} param $handler {{ }} '
                f'body {{ insert $handler into $handlers at {key}; }} }} }} select $unit; }}')
    assert len(search(tmp_path, keyed('$topic'), cache_mb=0)['rows']) == 1
    # The map is keyed by ``topic``; a different key spelling is a different insertion.
    assert search(tmp_path, keyed('"other"'), cache_mb=0)['rows'] == []


def test_indexed_insert_lands_in_the_bucket_of_that_key(tmp_path):
    write(tmp_path, 'class Bus:\n'
                    '    def __init__(self): self.handlers = {}; self.topic = "click"\n'
                    '    def subscribe(self, handler): self.handlers.setdefault(self.topic, []).append(handler)\n')
    named = 'field $registry { name: "handlers"; } field $topic { name: "topic"; }'
    bucket = query('insert $listener into $registry[$topic];', named)
    assert len(search(tmp_path, bucket, cache_mb=0)['rows']) == 1
    # A different key is a different bucket.
    other = query('insert $listener into $registry at "other";', named)
    assert search(tmp_path, other, cache_mb=0)['rows'] == []
    # Without a key the insertion still names the registry the bucket belongs to.
    assert len(search(tmp_path, query('insert $listener into $registry;', named), cache_mb=0)['rows']) == 1


def test_iterate_walks_the_bucket_and_invokes_its_elements(tmp_path):
    write(tmp_path, 'class Bus:\n'
                    '    def __init__(self): self.handlers = {}; self.topic = "click"\n'
                    '    def publish(self, payload):\n'
                    '        for handler in self.handlers.get(self.topic, []):\n'
                    '            handler(payload)\n')
    walked = ('language "kql/2"; module t; query q { '
              'type $unit { field $registry { name: "handlers"; } field $topic { name: "topic"; } '
              'method $publish { param $payload { } body { '
              'iterate $registry[$topic] as $handler { body { call $handler { argument $payload at 0; }; } } '
              '} } } select $unit; }')
    assert len(search(tmp_path, walked, cache_mb=0)['rows']) == 1
    # A different topic is a different bucket, so the walk is not the described one.
    wrong = walked.replace('iterate $registry[$topic]', 'iterate $registry[$other]').replace(
        'field $topic { name: "topic"; }', 'field $topic { name: "topic"; } field $other { name: "topicOut"; }')
    assert search(tmp_path, wrong, cache_mb=0)['rows'] == []


def test_keyed_iteration_walks_what_the_map_is_keyed_by(tmp_path):
    """``iterate keys of $registry as $key`` — Go's ``for key := range m``."""
    (tmp_path / 'a.go').write_text(
        'package sample\n'
        'type Listener interface { Receive(int) }\n'
        'type Hub struct { listeners map[Listener]Listener }\n'
        'func (h *Hub) Add(listener Listener) { h.listeners[listener] = listener }\n'
        'func (h *Hub) Notify(event int) {\n'
        ' for key, value := range h.listeners { key.Receive(event); _ = value }\n'
        '}\n')
    keyed = ('language "kql/2"; module t; query q { '
             'type $unit { field $registry { name: "listeners"; } method $notify { '
             'body { iterate keys of $registry as $key { body { } } } } } select $unit; }')
    assert len(search(tmp_path, keyed, cache_mb=0)['rows']) == 1
    # The unkeyed walk asks for the values, which this fixture never invokes.
    valued = ('language "kql/2"; module t; query q { '
              'type $unit { field $registry { name: "listeners"; } method $notify { '
              'body { iterate $registry as $value { body { } } } } } select $unit; }')
    assert len(search(tmp_path, valued, cache_mb=0)['rows']) == 1
    # The catalogue asserts the negative side in strict evidence mode; ``search`` reports
    # an unanalysable body as unknown, so the wrong-method case belongs to that harness.


def test_iterated_element_is_the_receiver_of_the_operation_it_offers(tmp_path):
    """``for (Op o : ops) o.apply(context)``: the element is an interface value."""
    (tmp_path / 'D.java').write_text(
        'import java.util.ArrayList;\n'
        'import java.util.List;\n'
        'import java.util.function.IntUnaryOperator;\n'
        'class Dispatcher {\n'
        '  private final List<IntUnaryOperator> pending = new ArrayList<>();\n'
        '  void run(int context) {\n'
        '    for (IntUnaryOperator action : pending) { action.applyAsInt(context); }\n'
        '  }\n'
        '}\n')

    def walked(call: str) -> str:
        return ('language "kql/2"; module t; query q { '
                'type $unit { field $pending { name: "pending"; } method $run { param $context { } '
                'body { iterate $pending as $element { body { ' + call + ' } } } } } '
                'select $unit; }')

    receiver = walked('call on $element { argument $context at 0; };')
    assert len(search(tmp_path, receiver, cache_mb=0)['rows']) == 1
    # Nothing is called *as* the element: the callable is the operation the element offers.
    as_callee = walked('call $element { argument $context at 0; };')
    assert search(tmp_path, as_callee, cache_mb=0)['rows'] == []
