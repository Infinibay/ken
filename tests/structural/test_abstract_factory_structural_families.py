"""Abstract Factory ``structural-families``: two providers by their slot set.

The variant is a published rule, so the tests go through the registry name
``abstract-factory#structural-families`` rather than a private copy of the query.

The providers do **not** share a base. What makes them a family is that they
declare the same creation slots, and the IR gets that from
``MATCHES_SIGNATURE`` (IR 1.69): a ``SIGNATURE`` entity per member name and arity
declared by two or more nominal types, so the query joins the two providers by
**identity** instead of pairing every method with every other method. That
cartesian join is the recorded reason this variant was still `design`:
``budget:max_states`` on a corpus of 30 types.

What is **not** resolved, and is stated in ``query_claim``: the JavaScript /
TypeScript object-literal provider (``const ocean = { createButton: () => ... }``).
The IR models an object literal as a ``COLLECTION`` of kind ``record``, not as a
type with members, so the arrow functions never acquire a member name. The class
form used here is also a JavaScript object with methods and needs no inheritance,
which is the property the variant is about.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'abstract-factory#structural-families'
ROOT = 'abstract-factory'
LANGUAGES = ['javascript', 'typescript', 'go']
EXTENSIONS = {'javascript': 'js', 'typescript': 'ts', 'go': 'go'}
NAMES = {'first': 'Ocean', 'second': 'Land',
         'product_a': 'OceanButton', 'product_b': 'OceanPanel',
         'product_c': 'LandButton', 'product_d': 'LandPanel',
         'slot_a': 'createButton', 'slot_b': 'createPanel'}
RENAMED = {'first': 'Forest', 'second': 'Desert',
           'product_a': 'ForestButton', 'product_b': 'ForestPanel',
           'product_c': 'DesertButton', 'product_d': 'DesertPanel',
           'slot_a': 'buildPartA', 'slot_b': 'buildPartB'}
# Every negative is a different way of breaking the family contract: the slots do
# not match by name, only one slot matches, a slot's product is shared across the
# families, or a slot's product is shared inside one family.
NEGATIVES = ['no-shared-slot', 'single-slot', 'same-product-across',
             'same-product-within']


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'structural-families')


def _plan(mode, names):
    """Which slot each provider declares, and what each slot returns."""
    n = names
    slots = {'first': {'a': n['slot_a'], 'b': n['slot_b']},
             'second': {'a': n['slot_a'], 'b': n['slot_b']}}
    products = {('first', 'a'): n['product_a'], ('first', 'b'): n['product_b'],
                ('second', 'a'): n['product_c'], ('second', 'b'): n['product_d']}
    declared = {'first': ['a', 'b'], 'second': ['a', 'b']}
    if mode == 'no-shared-slot':
        slots['second']['b'] = 'makePanel'
    elif mode == 'single-slot':
        declared['second'] = ['a']
        slots['second']['b'] = 'makePanel'
    elif mode == 'same-product-across':
        products[('second', 'a')] = n['product_a']
    elif mode == 'same-product-within':
        products[('first', 'b')] = n['product_a']
    elif mode != 'positive':
        raise AssertionError(mode)
    return slots, products, declared


def source(language, mode, names=None):
    n = names or NAMES
    slots, products, declared = _plan(mode, names or NAMES)
    methods = {}
    for provider in ('first', 'second'):
        methods[provider] = [(slots[provider][key], products[(provider, key)])
                             for key in declared[provider]]
    if language in {'javascript', 'typescript'}:
        text = ''.join(f'class {n[key]} {{}}\n'
                       for key in ('product_a', 'product_b', 'product_c', 'product_d'))
        text += '\n'
        for provider in ('first', 'second'):
            body = '\n'.join(
                (f'  {slot}(): {product} {{ return new {product}(); }}' if language == 'typescript'
                 else f'  {slot}() {{ return new {product}(); }}')
                for slot, product in methods[provider])
            text += f'class {n[provider]} {{\n{body}\n}}\n\n'
        return text
    if language == 'go':
        text = 'package abstractfactory\n\n'
        for key in ('product_a', 'product_b', 'product_c', 'product_d'):
            text += f'type {n[key]} struct{{}}\n'
        text += '\n'
        for provider in ('first', 'second'):
            text += f'type {n[provider]} struct{{}}\n'
            for slot, product in methods[provider]:
                text += (f'func ({n[provider]}) {slot[:1].upper() + slot[1:]}() {product} '
                         f'{{ return {product}{{}} }}\n')
            text += '\n'
        return text
    raise AssertionError(language)


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'family.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, (language, mode, graph.diagnostics)
    return graph


def detect(language, mode, names=None, rule=RULE):
    graph = build(language, mode, names)
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_structural_family_pair_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    units = {m['bindings']['$unit'] for m in matches}
    assert len(units) == 2, units
    # Both providers and both products of each pair are distinct entities. The
    # first provider is exported under the ``unit`` role, matching the other two
    # variants, so its binding is keyed by the role rather than by ``$first``.
    bindings = matches[0]['bindings']
    for role in ('$unit', '$second', '$first_slot', '$second_slot',
                 '$first_product', '$second_product', '$third_product', '$fourth_product'):
        assert role in bindings, (language, role)
    assert bindings['$unit'] != bindings['$second']
    assert bindings['$first_product'] != bindings['$second_product']
    assert bindings['$third_product'] != bindings['$fourth_product']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'positive', names=RENAMED)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'family.{EXTENSIONS[language]}::module/CLASS:{RENAMED["first"]}',
        f'family.{EXTENSIONS[language]}::module/CLASS:{RENAMED["second"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_both_providers(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert len({m['bindings']['$unit'] for m in matches}) == 2


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'MATCHES_SIGNATURE' in row['query']
    assert 'RETURNS_NEW' in row['query']


@pytest.mark.parametrize('language', LANGUAGES)
def test_shared_slot_is_one_entity_for_both_providers(language):
    """The join is by identity, not by comparing names.

    Two providers declaring the same member name and arity point at the *same*
    ``SIGNATURE`` entity, and a member name only one type declares gets none --
    without that, relating the two providers pairs every method with every other
    method, which is the recorded ``budget:max_states`` blocker.
    """
    graph = build(language, 'positive')
    types = {e.id: e for e in graph.entities.values() if e.kind in {'CLASS', 'INTERFACE'}}
    signatures = {f.subject: f.object for f in graph.facts
                  if f.relation == 'MATCHES_SIGNATURE'}
    declared = {}
    for fact in graph.facts:
        if fact.relation == 'HAS_METHOD' and fact.subject in types:
            declared.setdefault(types[fact.subject].name, set()).add(signatures.get(fact.object))
    assert declared['Ocean'] == declared['Land'], declared
    assert None not in declared['Ocean'], declared
    assert len(declared['Ocean']) == 2, declared
    # A member declared by a single type is not a shared slot.
    solo = {'javascript': 'class Solo {\n  only() { return 1; }\n}\n',
            'typescript': 'class Solo {\n  only(): number { return 1; }\n}\n',
            'go': 'package solo\n\ntype Solo struct{}\n\nfunc (Solo) Only() int { return 1 }\n'}[language]
    single = link_project([lower_source(solo, language, f'solo.{EXTENSIONS[language]}')])
    assert not [f for f in single.facts if f.relation == 'MATCHES_SIGNATURE']
