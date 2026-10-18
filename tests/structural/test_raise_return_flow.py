"""A terminal raise does not invalidate later normal-return provenance."""

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def _graph(body):
    """Analyze one wrapper without importing or executing its source."""
    return link_project(
        [lower_source(f"def wrapper(key):\n{body}", "python", "sample.py")]
    )


def _status(graph):
    """Read the explicit support decision for the selected function."""
    return next(
        fact
        for fact in graph.facts
        if fact.relation == "RETURN_FLOW_STATUS"
        and graph.entities[fact.subject].name == "wrapper"
    )


def test_raise_guard_keeps_the_only_normal_return_origin():
    """A terminal error branch cannot contribute a competing returned value."""
    graph = _graph(
        "    value = lookup(key)\n"
        "    if value is None:\n"
        "        raise KeyError(key)\n"
        "    return value\n"
    )
    assert not graph.diagnostics
    assert _status(graph).object == "supported"
    origins = [fact for fact in graph.facts if fact.relation == "RETURN_ORIGIN"]
    assert len(origins) == 1
    assert graph.entities[origins[0].object].name == "lookup"
    assert origins[0].attrs["modality"] == "must"


def test_unconditional_raise_makes_later_return_unreachable():
    """Stopping a path must not create a witness for dead source text."""
    graph = _graph(
        "    value = lookup(key)\n    raise KeyError(key)\n    return value\n"
    )
    assert _status(graph).object == "supported"
    assert not any(fact.relation == "RETURN_ORIGIN" for fact in graph.facts)


def test_write_on_raise_only_branch_cannot_reach_return():
    """An overwritten value on an exiting path cannot pollute the join."""
    graph = _graph(
        "    value = lookup(key)\n"
        "    if key is None:\n"
        "        value = other(key)\n"
        "        raise KeyError(key)\n"
        "    return value\n"
    )
    assert _status(graph).object == "supported"
    origins = [fact for fact in graph.facts if fact.relation == "RETURN_ORIGIN"]
    assert len(origins) == 1
    assert graph.entities[origins[0].object].name == "lookup"
    assert origins[0].attrs["modality"] == "must"


def test_raise_inside_try_stays_unsupported():
    """A handler can restore normal execution, so try needs another model."""
    graph = _graph(
        "    value = lookup(key)\n"
        "    try:\n"
        "        raise KeyError(key)\n"
        "    except KeyError:\n"
        "        pass\n"
        "    return value\n"
    )
    assert _status(graph).object == "unsupported"
    assert not any(fact.relation == "RETURN_ORIGIN" for fact in graph.facts)


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "javascript",
            (
                "function wrapper(key) { let value = lookup(key); "
                "if (value == null) { throw new Error(); } return value; }"
            ),
        ),
        (
            "typescript",
            (
                "function wrapper(key: unknown) { let value = lookup(key); "
                "if (value == null) { throw new Error(); } return value; }"
            ),
        ),
        (
            "java",
            (
                "class A { Object wrapper(Object key) { Object value = lookup(key); "
                "if (value == null) { throw new RuntimeException(); } return value; } }"
            ),
        ),
        (
            "csharp",
            (
                "class A { object wrapper(object key) { object value = lookup(key); "
                "if (value == null) { throw new Exception(); } return value; } }"
            ),
        ),
    ],
)
def test_terminal_throw_preserves_normal_return_across_languages(language, source):
    """The same terminal-path rule applies to supported throw statements."""
    graph = link_project([lower_source(source, language, "sample")])
    assert not graph.diagnostics
    assert _status(graph).object == "supported"
    origins = [fact for fact in graph.facts if fact.relation == "RETURN_ORIGIN"]
    assert len(origins) == 1
    assert origins[0].attrs["modality"] == "must"
