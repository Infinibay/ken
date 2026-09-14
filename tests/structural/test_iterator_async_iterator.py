"""Iterator ``async-iterator``: a suspending loop over a suspending producer.

The variant is a published rule, so the test goes through the registry name
``iterator#async-iterator`` rather than a private copy of the query.

What the IR could not say before 1.59 is the one thing that distinguishes this
from a plain iterator: a loop that **suspends** to advance. ``async for``, ``for
await`` and ``await foreach`` already produced ``LOOP``, ``ITERATION_SOURCE`` and
``ITERATION_BODY`` — exactly the facts a synchronous loop over the same source
produces. The async-ness lived only in the unnamed token list, which no query can
see, so it is now recorded on the loop itself as ``async``.

The producer half was already expressible: an async callable that yields. The
contract additionally requires it to ``await`` while advancing, which is the
concrete reading of "producción/avance ... se rigen por protocolo async" and the
reason ``await`` cannot be silently reinterpreted as blocking work.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'iterator#async-iterator'
LANGUAGES = ['python', 'javascript', 'typescript', 'csharp']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'csharp': 'cs'}

SOURCES = {
    'python': '''async def produce():
    for index in range(3):
        yield await fetch(index)

async def consume():
    async for item in produce():
        await handle(item)
''',
    'javascript': '''async function* produce() {
  for (let i = 0; i < 3; i++) {
    yield await fetch(i);
  }
}

async function consume() {
  for await (const item of produce()) {
    await handle(item);
  }
}
''',
    'typescript': '''async function* produce(): AsyncGenerator<number> {
  for (let i = 0; i < 3; i++) {
    yield await fetch(i);
  }
}

async function consume(): Promise<void> {
  for await (const item of produce()) {
    await handle(item);
  }
}
''',
    'csharp': '''class Source {
    async IAsyncEnumerable<int> Produce() {
        for (int i = 0; i < 3; i++) {
            yield return await Fetch(i);
        }
    }

    async Task Consume() {
        await foreach (var item in this.Produce()) {
            await Handle(item);
        }
    }
}
''',
}

# The synchronizing loop is the whole difference: same source, same body, same
# iteration facts, no suspension.
SYNC_LOOP = {
    'python': SOURCES['python'].replace('async for item', 'for item'),
    'javascript': SOURCES['javascript'].replace('for await (const item of', 'for (const item of'),
    'typescript': SOURCES['typescript'].replace('for await (const item of', 'for (const item of'),
    'csharp': SOURCES['csharp'].replace('await foreach', 'foreach'),
}

SYNC_PRODUCER = {
    'python': SOURCES['python'].replace('async def produce', 'def produce'),
    'javascript': SOURCES['javascript'].replace('async function* produce', 'function* produce'),
    'typescript': SOURCES['typescript'].replace('async function* produce', 'function* produce'),
    'csharp': SOURCES['csharp'].replace('async IAsyncEnumerable<int> Produce',
                                        'IEnumerable<int> Produce'),
}

PY_NOT_A_GENERATOR = '''async def produce():
    return 1

async def consume():
    async for item in produce():
        await handle(item)
'''

PY_NEVER_AWAITS = '''async def produce():
    yield 1

async def consume():
    async for item in produce():
        handle(item)
'''

PY_ASYNC_LOOP_OVER_SYNC_SOURCE = '''def produce():
    yield 1

async def consume():
    async for item in produce():
        await handle(item)
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'iterator')
    return next(v for v in rule.variants if v['id'] == 'async-iterator')


def detect(language, source):
    graph = link_project([lower_source(source, language, f'iterator.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_suspending_loop_over_suspending_producer_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role is the consumer, matching the other iterator variants: the
    # exported name is ``iterator`` even though the consumer is what it names.
    assert '/CALLABLE:' in bindings['$iterator']
    assert bindings['$producer'] != bindings['$iterator']
    assert '/CALL' in bindings['$source']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_synchronous_loop_over_the_same_source_is_rejected(language):
    """The variant's whole content: the loop must suspend, not just iterate."""
    assert not detect(language, SYNC_LOOP[language]), language


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_synchronous_producer_is_rejected(language):
    assert not detect(language, SYNC_PRODUCER[language]), language


def test_an_async_callable_that_never_yields_is_rejected():
    assert not detect('python', PY_NOT_A_GENERATOR)


def test_a_declared_async_iterator_that_never_awaits_is_rejected():
    """Both sides can carry the ``async`` keyword and still drive nothing.

    Requiring an ``await`` in the producer is what separates a declared async
    generator from one whose advance is actually governed by the protocol.
    """
    assert not detect('python', PY_NEVER_AWAITS)


def test_an_async_loop_over_a_synchronous_source_is_rejected():
    assert not detect('python', PY_ASYNC_LOOP_OVER_SYNC_SOURCE)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'async: true' in row['query'] and 'ITERATION_SOURCE' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_loop_itself_records_the_suspension(language):
    """No other fact separates an async loop from a synchronous one.

    ``ITERATION_SOURCE``, ``ITERATION_BODY`` and the loop kind are identical for
    ``for (const item of produce())``; only the loop's own ``async`` flag differs.
    Each fixture also contains the producer's plain count loop, which must stay
    unflagged -- that is what makes the flag a property of the loop rather than of
    the enclosing callable.
    """
    ext = EXTENSIONS[language]
    for label, text, expected_async in [('async', SOURCES[language], 1),
                                        ('sync', SYNC_LOOP[language], 0)]:
        graph = link_project([lower_source(text, language, f'iterator.{ext}')])
        loops = [op for op in graph.operations if op.kind == 'LOOP']
        assert len(loops) == 2, (language, label, len(loops))
        async_loops = [op for op in loops if op.attrs.get('async')]
        assert len(async_loops) == expected_async, (language, label)
