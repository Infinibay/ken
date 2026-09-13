"""Graph cache reuse must preserve content identity and unit-level invalidation."""
import pytest

from ken.structural import service
from ken.structural.kenql import query_graph


@pytest.mark.parametrize('change', ['edit', 'add', 'delete'])
def test_graph_miss_reuses_unchanged_units(tmp_path, monkeypatch, change):
    (tmp_path / 'a.py').write_text('class A: pass\n')
    (tmp_path / 'b.py').write_text('class B: pass\n')
    service.build_project(tmp_path)
    parsed = []
    linked = []
    original_lower, original_link = service.lower_source, service.link_project

    def lower(text, language, path):
        parsed.append(path)
        return original_lower(text, language, path)

    def link(units):
        linked.append(len(units))
        return original_link(units)

    monkeypatch.setattr(service, 'lower_source', lower)
    monkeypatch.setattr(service, 'link_project', link)
    if change == 'edit':
        (tmp_path / 'b.py').write_text('class Changed: pass\n')
    elif change == 'add':
        (tmp_path / 'c.py').write_text('class C: pass\n')
    else:
        (tmp_path / 'b.py').unlink()
    graph, analysis = service.build_project(tmp_path)
    assert parsed == {'edit': ['b.py'], 'add': ['c.py'], 'delete': []}[change]
    assert linked == [{'edit': 2, 'add': 3, 'delete': 1}[change]]
    assert analysis['cache']['hits'] == {'edit': 1, 'add': 2, 'delete': 1}[change]
    fresh, _ = service.build_project(tmp_path, cache_mb=0)
    assert graph.to_dict() == fresh.to_dict()


def test_parser_revision_invalidates_graph_and_units(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class A: pass\n')
    monkeypatch.setattr(service, '_parser_versions', lambda: 'parser-one')
    graph, _ = service.build_project(tmp_path)
    monkeypatch.setattr(service, '_parser_versions', lambda: 'parser-two')
    reloaded, stats = service.build_project(tmp_path)
    assert stats['cache']['hits'] == 0
    assert stats['cache']['misses'] == 2
    assert reloaded.to_dict() == graph.to_dict()


def test_query_projection_and_caller_mutations_do_not_poison_cached_graph(tmp_path):
    (tmp_path / 'a.py').write_text('def make(value):\n return consume(value)\n')
    graph, _ = service.build_project(tmp_path)
    source = graph.to_dict()
    projected = query_graph(graph)
    assert projected.ir.view == 'query'
    assert graph.to_dict() == source
    graph.entities.clear()
    graph.facts.clear()
    graph.operations.clear()
    restored, stats = service.build_project(tmp_path)
    assert stats['cache']['hits'] == 1
    assert restored.to_dict() == source
