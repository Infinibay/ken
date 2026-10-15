from ken.retrieval.model import CodeMatch, EntityKey, Passage, SearchRequest, Span


def example(lines, regions):
    entity = EntityKey('client.py', 'function', 'run')
    evidence = [Passage(entity, r, {'body': '\n'.join(lines[r.start_line-1:r.end_line]),
                                  'signature': 'def run(value):'}, 'a' * 64,
                        Span(1, len(lines)), implementation_start_line=1) for r in regions]
    return CodeMatch(entity, 0., evidence, 'a' * 64, owned_regions=tuple(regions))


def proposals(match, lines, query='handle value', **kwargs):
    from ken.retrieval.window_proposals import propose_windows
    return propose_windows(match, lines, SearchRequest(query), query=query,
                           stem_words=lambda words: words, **kwargs)


def test_short_implementation_is_a_complete_source_hypothesis():
    lines = ['def run(value):', '    if value is None:', '        return 0', '    return value']
    bundles = proposals(example(lines, [Span(1, 4)]), lines)
    assert any([p.span for p in bundle] == [Span(1, 4)] for bundle in bundles)


def test_proposals_preserve_complete_statement_support_after_distracting_prefix():
    lines = ['process value'] * 80
    lines[44] = 'if value is None:'
    lines[66] = '    return value'
    bundles = proposals(example(lines, [Span(1, 80)]), lines,
                        statements=[Span(45, 67)])
    assert any(any(p.span.start_line <= 45 and p.span.end_line >= 67 for p in b) for b in bundles)
    assert len(bundles) <= 12


def test_every_hypothesis_has_at_most40_lines_and_preserves_nested_owner_gaps():
    lines = ['process value'] * 100
    regions = [Span(1, 30), Span(50, 100)]
    bundles = proposals(example(lines, regions), lines, statements=[Span(20, 60)])
    assert bundles
    for bundle in bundles:
        assert sum(p.span.end_line-p.span.start_line+1 for p in bundle) <= 40
        for p in bundle:
            assert any(r.start_line <= p.span.start_line <= p.span.end_line <= r.end_line
                       for r in regions)
            assert p.fields['body'] == '\n'.join(lines[p.span.start_line-1:p.span.end_line])
            assert p.signals['selected_window'] == 1.
        assert all(a.span.end_line < b.span.start_line for a, b in zip(bundle, bundle[1:]))


def test_named_identity_proposes_the_actual_declaration():
    lines = ['class Runtime:'] + ['    value = 1'] * 80
    match = example(lines, [Span(1, 81)])
    bundles = proposals(match, lines, query='Show the Runtime class declaration.')
    assert bundles[0][0].span.start_line == 1


def test_missing_region_metadata_cannot_fill_an_unobserved_child_body():
    from dataclasses import replace
    lines = ['process value'] * 100
    regions = [Span(1, 2), Span(50, 100)]
    match = replace(example(lines, regions), owned_regions=())
    for bundle in proposals(match, lines):
        for passage in bundle:
            assert any(r.start_line <= passage.span.start_line <= passage.span.end_line <= r.end_line
                       for r in regions)
