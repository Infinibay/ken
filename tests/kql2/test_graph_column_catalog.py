"""Each catalogue rule must retain findings and evidence on native storage."""

import json

import pytest

from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project
from ken.structural_store import Store
from tests.kql2.test_graph_columns import stored
from tests.structural.test_gof_executable import MUTATIONS, SOURCES


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        return (
            sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
            if all(isinstance(item, dict) for item in items)
            else items
        )
    return value


@pytest.fixture(scope="module")
def queries():
    return query_registry(builtin_rules())


@pytest.mark.parametrize("language", sorted(SOURCES))
@pytest.mark.parametrize("name", sorted(SOURCES["python"]))
@pytest.mark.parametrize("mutation", [False, True])
def test_catalogue_backend_equivalence(language, name, mutation, queries):
    source = SOURCES[language][name]
    if mutation:
        if name not in MUTATIONS.get(language, {}):
            pytest.skip("no authored mutation for this language")
        source = source.replace(*MUTATIONS[language][name])
    suffix = {"python": "py", "java": "java", "typescript": "ts"}[language]
    memory = query_graph(
        link_project([lower_source(source, language, "sample." + suffix)])
    )

    def run(index):
        engine = Executor(index, queries)
        try:
            outcome = engine.execute(queries[name])
            return canonical(
                {key: outcome[key] for key in ("complete", "matches", "unknown")}
            )
        finally:
            engine.close()

    expected = run(memory)
    assert expected["complete"]
    with Store(cache_mb=0) as store:
        assert run(stored(store, memory.ir)) == expected
