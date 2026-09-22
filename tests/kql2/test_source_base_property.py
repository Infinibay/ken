"""``class $d { base: $p; }`` — the runtime base a locally created type carries.

The legacy catalogue stated this with ``edge BASE_INPUT($derived, $base)``.  This is
the KQL 2 spelling of the same claim: the type the pattern bound was created from a
place the pattern also bound, and the analysis proved that place is an unreassigned
parameter of the declaring callable.  It is *not* an inheritance spelling: a nominal
``extends Other`` never publishes ``BASE_INPUT``.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(base: str = '$base', returns: str = 'where returns_value($factory, $derived);') -> str:
    return ('language "kql/2"; module t; '
            'pattern detect(out GraphTerm $factory, out GraphTerm $derived, out GraphTerm $base) { '
            'callable $factory { param $base { reassigned: false; } '
            f'class $derived {{ base: {base}; }} }} '
            f'{returns} }} '
            'query q { use detect(factory: $factory, derived: $derived, base: $base); '
            'select $factory, $derived, $base; }')


def write(tmp_path, source: str) -> None:
    (tmp_path / 'mixin.py').write_text(source)


SUPPLIED_BASE = ('def extend(base):\n'
                 '    class Derived(base):\n'
                 '        def render(self): return 1\n'
                 '    return Derived\n')


def test_a_returned_local_class_built_on_a_parameter_matches(tmp_path):
    write(tmp_path, SUPPLIED_BASE)
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_a_reassigned_base_parameter_is_not_the_supplied_base(tmp_path):
    # ``BASE_INPUT`` is only published for a place that is never written, so a base
    # rebound before the class is created is a different (unproven) derivation.
    write(tmp_path, 'def extend(base):\n'
                    '    base = object()\n'
                    '    class Derived(base):\n'
                    '        pass\n'
                    '    return Derived\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_a_class_built_on_a_nominal_class_is_not_a_supplied_base(tmp_path):
    write(tmp_path, 'class Other: pass\n'
                    'def extend(base):\n'
                    '    class Derived(Other):\n'
                    '        pass\n'
                    '    return Derived\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_a_factory_that_does_not_return_the_class_does_not_match(tmp_path):
    # ``returns_value`` is what separates the class itself from an instance of it or
    # from any other value the factory hands back.
    write(tmp_path, 'def extend(base):\n'
                    '    class Derived(base):\n'
                    '        pass\n')
    assert search(tmp_path, query(), cache_mb=0)['rows'] == []
    write(tmp_path, 'def extend(base):\n'
                    '    class Derived(base):\n'
                    '        pass\n'
                    '    return Derived()\n')
    assert search(tmp_path, query(), cache_mb=0)['rows'] == []


def test_base_requires_a_place_role(tmp_path):
    write(tmp_path, SUPPLIED_BASE)
    # A literal is not a place: the property names the runtime base the analysis
    # tracked, so a spelling that cannot be tracked is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query(base='"Other"'), cache_mb=0)
