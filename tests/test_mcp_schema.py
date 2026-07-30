"""The JSON Schema ken derives for its own tools.

ken has two schema derivations, not one. ``ken mcp`` serves the SDK's
pydantic-derived schema, and ``list_tools()`` — which backs ``ken tools``
and the daemon — uses the hand-rolled one in ``ken.mcp.server``. When they
disagree, the divergence is silent: the agent gets a correct schema while
the CLI gets a degraded one, so nothing fails loudly.

The shape that exposed this was ``list[Literal[...]] | None``. PEP 604's
``X | None`` reports ``types.UnionType`` from ``typing.get_origin`` while
``Optional[X]`` reports ``typing.Union``, and matching only the second
collapsed the whole parameter to ``{}`` — which argparse then read as a
plain string, so ``--include symbols`` arrived as six single characters.
"""

from __future__ import annotations

import inspect
import typing

import pytest

from ken.mcp.server import _annotation_to_schema, list_tools


def _schema(annotation, default=inspect.Parameter.empty):
    param = inspect.Parameter(
        "p", inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
    )
    return _annotation_to_schema(param, annotation)


# ── the two spellings of a union ─────────────────────────────────────────


@pytest.mark.parametrize(
    "annotation",
    [list[str] | None, typing.Optional[list[str]]],
    ids=["pep604", "optional"],
)
def test_both_union_spellings_survive_the_unwrap(annotation):
    """``X | None`` and ``Optional[X]`` are different objects until Python
    3.14 unifies them; the derivation must not care which one was written."""
    schema, has_default = _schema(annotation, default=None)
    assert schema == {"type": "array", "items": {"type": "string"}}
    assert has_default is True


def test_an_optional_parameter_is_not_required():
    """``has_default`` is what puts a parameter in ``required``. A union
    that failed to unwrap reported False and made the argument mandatory."""
    _, has_default = _schema(str | None)
    assert has_default is True


def test_optional_primitives_keep_their_type():
    schema, _ = _schema(int | None, default=None)
    assert schema == {"type": "integer"}


# ── enums ────────────────────────────────────────────────────────────────


def test_a_literal_becomes_a_typed_enum():
    schema, _ = _schema(typing.Literal["a", "b"], default="a")
    assert schema == {"enum": ["a", "b"], "type": "string", "default": "a"}


def test_a_list_of_literals_keeps_the_element_enum():
    """The element enum is the only place that says which values the list
    may hold — without it a caller has to guess from prose."""
    schema, _ = _schema(list[typing.Literal["symbols", "source"]] | None, default=None)
    assert schema == {
        "type": "array",
        "items": {"enum": ["symbols", "source"], "type": "string"},
    }


# ── the published surface ────────────────────────────────────────────────


def test_no_registered_tool_publishes_an_empty_parameter():
    """The guard that would have caught this class of bug at the source: an
    empty schema is indistinguishable from an untyped free-form string, and
    every degraded parameter reaches an agent that way."""
    blank = [
        f"{tool.name}.{name}"
        for tool in list_tools()
        for name, prop in tool.parameters.get("properties", {}).items()
        if not ({"type", "enum", "anyOf"} & set(prop))
    ]
    assert blank == []
