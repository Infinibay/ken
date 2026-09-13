"""The instruction adapter must preserve source provenance across all 23 GoF."""
import json

import pytest

from ken.structural import lower_source, link_project, lower_instructions
from ken.structural.instructions import Program
from .test_gof_executable import SOURCES


@pytest.mark.parametrize('language', sorted(SOURCES))
@pytest.mark.parametrize('pattern', sorted(SOURCES['python']))
def test_each_gof_exports_without_mutating_source_or_losing_occurrence_provenance(language, pattern):
    graph = link_project([lower_source(SOURCES[language][pattern], language, pattern)])
    before = graph.to_dict()
    program = lower_instructions(graph)
    assert program.functions
    assert graph.to_dict() == before
    assert {f.id for f in program.functions} == {e.id for e in graph.entities.values() if e.kind=='CALLABLE'}
    nodes = {op.id:op for op in graph.operations}
    for f in program.functions:
        regions=[f.body]
        for region in regions:
            for i in region.instructions:
                source=nodes[i.source['operation']]
                assert source.owner == f.id
                assert (i.source['start'],i.source['end']) == (source.start,source.end)
                if i.opcode == 'native':
                    assert f.status=='partial' and f.reasons
                    assert 'unknown' in i.effects
                regions.extend(i.regions)
    assert Program.from_dict(json.loads(json.dumps(program.to_dict()))).to_dict() == program.to_dict()
