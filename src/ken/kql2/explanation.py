"""Compile-only authoring support: no project acquisition or source execution."""

from .compiler import PROPERTIES, compile
from .diagnostics import diagnose
from .syntax import parse
from .syntax_schema import (
    SYNTAX_PROPERTIES,
    SYNTAX_RELATIONS,
    SYNTAX_SELECTORS,
    syntax_kinds,
)


def capabilities() -> dict:
    return {
        "language": "kql/2",
        "backends": {
            "exploration": {
                "selectors": list(SYNTAX_SELECTORS),
                "properties": SYNTAX_PROPERTIES,
                "relations": sorted(SYNTAX_RELATIONS),
                "body": False,
                "graph": False,
                "meaning": "Syntax structure and spelling; no call resolution or implicit control flow.",
            },
            "indexed": {
                "selector_properties": PROPERTIES,
                "body": True,
                "graph": True,
                "meaning": "Source declarations, supported BODY value/CFG patterns and graph relations; preparation can require project linking.",
            },
        },
        "syntax_kinds": sorted(syntax_kinds()),
        "containment": {
            "nested_node": "immediate child",
            "contains_direct": "immediate child",
            "contains": "strict descendant",
        },
        "literal_matching": 'Python: kind: "literal"; text: "True"; or text: "None";',
        "limits": "Parser grammar is broader than each backend. Use --explain on the complete query to validate executable support.",
    }


def explain(source, *, query_name=None, backend="indexed", libraries=None) -> dict:
    from .catalog import with_packaged_libraries
    from .execution import prepare

    libraries = with_packaged_libraries(source, libraries)
    program = compile(
        parse(source),
        query_name,
        libraries={name: parse(text, name) for name, text in libraries.items()},
    )
    if backend == "exploration":
        from .exploration.compiler import compile_plan

        compile_plan(program)
    elif backend == "indexed":
        for branch in program.branches or (program,):
            prepare(branch)
    else:
        raise ValueError("unknown backend: " + backend)
    return {
        "language": "kql/2",
        "query": program.name,
        "backend": backend,
        "validated": True,
        "executed": False,
        "diagnostics": diagnose(program),
        "columns": [
            expr.value or f"column_{i + 1}" for i, expr in enumerate(program.projection)
        ],
        "diagnostic_scope": "source capture relationships; graph authoring warnings are not covered",
        "claim": "Valid for this backend. Query validity and complete source coverage do not prove that the intended question is encoded or that runtime behavior is correct.",
    }
