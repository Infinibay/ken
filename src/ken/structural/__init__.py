"""Structural code intelligence: tree-sitter IR, graph queries and catalogues."""
from .frontend import lower_file, lower_source
from .model import IR, IR_VERSION, FactIndex
from .query import QueryBudget, evaluate_pattern
from .selectors import parse_query
from .semantic import link_project
from .instruction_lowering import lower_instructions

__all__ = ["IR", "IR_VERSION", "FactIndex", "QueryBudget", "evaluate_pattern", "lower_file",
           "lower_source", "parse_query", "link_project"]


def evaluate_query(ir: IR, query: str, *, named_queries: dict[str, str] | None = None,
                   budget: QueryBudget | None = None, evidence_mode: str = "strict"):
    """Evaluate KenQL against an IR, with optional named query dependencies."""
    from .kenql import Engine, parse, query_graph
    from .rules import builtin_rules, query_registry
    registry = query_registry(builtin_rules())
    for name, source in (named_queries or {}).items():
        if name in registry:
            raise ValueError(f"reserved query id: {name}")
        registry[name] = parse(source)
    return Engine(query_graph(ir), registry, budget, evidence_mode).execute(parse(query))


__all__.append("evaluate_query")
__all__.append("lower_instructions")
