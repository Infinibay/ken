"""Pure lowering from typed KQL2 to exploration instructions and predicates."""

import json
from dataclasses import dataclass

from ..compiler import Action, Program, Scan
from ..syntax_schema import SYNTAX_SELECTORS, property_hint
from .expressions import UnsupportedExploration, compile_expression, links, may_fail
from .tree import PROPERTIES


@dataclass(frozen=True)
class Test:
    name: str
    value: object
    regex: object = None


@dataclass(frozen=True)
class Explore:
    role: str
    selector: str
    owner: str | None
    tests: tuple[Test, ...]

    @property
    def exact(self):
        return {test.name: test.value for test in self.tests if test.regex is None}


@dataclass(frozen=True)
class Calculate:
    role: str
    evaluate: object


@dataclass(frozen=True)
class ExplorationPlan:
    program: Program
    instructions: tuple[Explore | Calculate, ...]
    relations: tuple[tuple[str, str, bool], ...]
    projection: tuple
    ordering: tuple
    branches: tuple = ()


def compile_plan(program):
    if program.graph:
        raise UnsupportedExploration(
            "relational graph queries; use the indexed backend until their semantics are ported"
        )
    if program.predicates or program.enums or program.optional:
        raise UnsupportedExploration(
            "recursive predicates, enum domains or optional evidence"
        )
    if program.branches:
        return ExplorationPlan(
            program, (), (), (), (), tuple(compile_plan(b) for b in program.branches)
        )
    instructions = []
    conditions = [*program.filters]
    steps = program.steps or (
        *program.scans,
        *(
            Action(role, expr)
            for role, expr in (
                program.actions or tuple(("", f) for f in program.filters)
            )
        ),
    )
    for step in steps:
        if isinstance(step, Scan):
            if step.selector not in SYNTAX_SELECTORS:
                raise UnsupportedExploration(
                    "selector "
                    + step.selector
                    + "; use --backend indexed for declarations or BODY value flow, or node kind constraints for syntax-only queries"
                )
            tests = []
            for key, expr in step.properties:
                if key not in PROPERTIES:
                    raise UnsupportedExploration("property " + key + ". " + property_hint(key), expr.span)
                if expr.kind == "wildcard":
                    continue
                if expr.kind not in ("literal", "regex"):
                    raise UnsupportedExploration(
                        "nonliteral scan constraint", expr.span
                    )
                tests.append(
                    Test(
                        key,
                        json.loads(expr.value) if expr.kind == "literal" else None,
                        expr if expr.kind == "regex" else None,
                    )
                )
            instructions.append(
                Explore(step.role, step.selector, step.owner, tuple(tests))
            )
        elif isinstance(step, Action):
            if not step.role:
                conditions.append(step.expression)
            instructions.append(
                Calculate(step.role, compile_expression(step.expression))
            )
        else:
            raise UnsupportedExploration(
                "CFG BODY clauses; use --backend indexed for BODY value flow, or nested node selectors for immediate syntax children"
            )
    # Conservative until hints have per-stage dominance information: a later
    # filter must not eliminate an earlier arithmetic/regex error by pruning its
    # input bindings. Calculation order alone does not prevent that rewrite.
    barriers = any(
        may_fail(step.expression)
        if isinstance(step, Action)
        else any(may_fail(expr) for _, expr in step.properties)
        for step in steps
    )
    return ExplorationPlan(
        program,
        tuple(instructions),
        () if barriers else tuple(links(conditions)),
        tuple(compile_expression(e.args[0]) for e in program.projection),
        tuple(compile_expression(e.args[0]) for e in program.ordering),
    )
