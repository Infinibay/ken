"""GoF structural signatures, all executed by the public graph query engine.

These recognize evidence consistent with an idiom. They do not prove design
intent, uniqueness, correctness or complete coverage of its implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import FactIndex, IR
from .query import Pattern, QueryBudget, evaluate_pattern, parse_pattern


@dataclass
class Rule:
    id: str
    name: str
    category: str
    description: str
    query: str
    caveat: str = "Structural evidence requires review of intent and runtime behavior."

    legacy_query: str = ""

    variants: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    operations: list[dict[str, str]] = field(default_factory=list)
    query_language: str = "kenql/1"

    def pattern(self) -> Pattern:
        return parse_pattern(f"pattern {self.name}\n" + (self.legacy_query or self.query))


def _load_catalog() -> list[Rule]:
    from importlib.resources import files
    import tomllib
    result = []
    for path in sorted(files("ken.structural").joinpath("patterns").iterdir(), key=lambda p: p.name):
        if path.name.endswith(".toml"):
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            result.append(Rule(**{k: data[k] for k in Rule.__dataclass_fields__ if k in data}, source=str(path)))
    return result


RULES = _load_catalog()


def catalog() -> list[dict[str, Any]]:
    return [{"id": r.id, "name": r.name, "category": r.category,
             "description": r.description, "query": r.query.strip(),
             "query_language": r.query_language,
             **({"legacy_id": "legacy.gof." + r.id} if r.legacy_query else {}),
             "executable_variants": [v["id"] for v in r.variants if v.get("status") == "ready"],
             "planned_variants": [v["id"] for v in r.variants if v.get("status") != "ready"], "caveat": r.caveat, "variants": r.variants, "operations": r.operations, "source": r.source} for r in RULES]


def detect_patterns(ir: IR | FactIndex, names: list[str] | None = None,
                    budget: QueryBudget | None = None, *, legacy: bool = False,
                    cache: Any = None, graph_key: str = "") -> dict[str, Any]:
    from .rules import builtin_rules, execute_rules, select_rules
    registry = builtin_rules()
    if legacy:
        from dataclasses import replace
        historical = {r.id: r.legacy_query for r in RULES}
        registry = [replace(r, query=historical[r.id], query_language='kenql/1') if historical.get(r.id) else r for r in registry]
    selected = select_rules(registry, ids=names, collections=["gof"])
    result = execute_rules(ir, selected, budget, registry=registry, cache=cache, graph_key=graph_key)
    metadata = {r.id: r for r in RULES}
    findings = [{**m, "category": metadata[m["id"]].category, "caveat": metadata[m["id"]].caveat}
                for m in result["matches"]]
    # A rule that exhausted its budget reports zero matches for the wrong reason:
    # "not found" and "not searched" must not look the same to a caller.
    incomplete = {rule: outcome["unknown"] for rule, outcome in result["outcomes"].items()
                  if not outcome["complete"]}
    return {"findings": findings, "outcomes": result["outcomes"], "complete": result["complete"],
            "incomplete": incomplete}
