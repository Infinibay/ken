"""A bounded graph query language. No eval, source execution, or embeddings."""
from __future__ import annotations

import fnmatch
import json
import re
import shlex
import time
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any

from .model import Fact, FactIndex, IR


@dataclass
class Clause:
    mode: str
    subject: str
    relation: str
    object: str
    attrs: list[tuple[str, str, str]] = field(default_factory=list)
    minimum: int = 1
    maximum: int = 1
    count_op: str = ">="
    count: int = 1
    distinct: str = ""
    where: list[Clause] = field(default_factory=list)
    capability: str = ""


@dataclass
class Pattern:
    name: str
    clauses: list[Clause] = field(default_factory=list)
    different: list[tuple[str, str]] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)
    variants: dict[str, list[Clause]] = field(default_factory=dict)


def _clause(words: list[str], mode: str) -> Clause:
    if len(words) < 3:
        raise ValueError("a clause requires SUBJECT RELATION OBJECT")
    subject, relation, object, *attrs = words
    m = re.fullmatch(r"([A-Z][A-Z_0-9]*)(?:\{(\d+),(\d+)\}|(\+|\*))?", relation)
    if not m:
        raise ValueError(f"invalid relation: {relation}")
    low, high = (int(m[2]), int(m[3])) if m[2] else ((1, 16) if m[4] else (1, 1))
    if not 1 <= low <= high <= 32:
        raise ValueError("path bounds must satisfy 1 <= min <= max <= 32")
    clause = Clause(mode, subject, m[1], object, minimum=low, maximum=high)
    for attr in attrs:
        a = re.fullmatch(r"([\w.]+)(!=|>=|<=|~=|=|>|<)(.+)", attr)
        if not a:
            raise ValueError(f"invalid attribute: {attr}")
        if a[1] == "when_capability":
            clause.capability = a[3]
        else:
            clause.attrs.append((a[1], a[2], a[3]))
    return clause


def parse_pattern(source: str, *, validate_roles: bool = True) -> Pattern:
    pattern = Pattern("query")
    current = pattern.clauses
    for number, line in enumerate(source.splitlines(), 1):
        words = shlex.split(line, comments=True)
        if not words:
            continue
        directive, *args = words
        try:
            if directive == "pattern":
                pattern.name = " ".join(args)
            elif directive == "scope" and args == ["project"]:
                pass
            elif directive == "capability" and args:
                pattern.capabilities.update(args)
            elif directive == "different" and len(args) == 2:
                pattern.different.append((args[0], args[1]))
            elif directive == "variant" and len(args) == 1:
                if current is not pattern.clauses or args[0] in pattern.variants:
                    raise ValueError("nested or duplicate variant")
                current = pattern.variants.setdefault(args[0], [])
            elif directive == "end" and not args and current is not pattern.clauses:
                current = pattern.clauses
            elif directive in {"require", "optional", "forbid"}:
                current.append(_clause(args, directive))
            elif directive == "count":
                comparison = re.fullmatch(r"(>=|<=|=|>|<)(\d+)", args.pop(0))
                if comparison is None:
                    raise ValueError("count requires a comparison such as >=2")
                where = args.index("where") if "where" in args else len(args)
                main, extra = args[:where], args[where + 1:]
                distinct = next((a.split("=", 1)[1] for a in main if a.startswith("distinct=")), "")
                c = _clause([a for a in main if not a.startswith("distinct=")], "count")
                c.count_op, c.count, c.distinct = comparison[1], int(comparison[2]), distinct
                groups: list[list[str]] = [[]]
                for word in extra:
                    if word == "and":
                        groups.append([])
                    else:
                        groups[-1].append(word)
                c.where = [_clause(g, "require") for g in groups if g]
                current.append(c)
            else:
                raise ValueError(f"unknown or malformed directive: {directive}")
        except (ValueError, IndexError) as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    if current is not pattern.clauses:
        raise ValueError("unterminated variant")
    if not any(c.mode == "require" for c in pattern.clauses) and not pattern.variants:
        raise ValueError("a pattern needs at least one required clause")
    # Negation and cardinality may introduce local variables, but different must
    # compare roles bound by required clauses; otherwise absence proves nothing.
    for variant in pattern.variants.values() or [[]]:
        bound = {t for c in pattern.clauses + variant if c.mode == "require"
                 for t in (c.subject, c.object) if t.startswith("$") or t == "@unit"}
        if validate_roles and any(a not in bound or b not in bound for a, b in pattern.different):
            raise ValueError("different requires two roles bound by required clauses")
    return pattern


@dataclass
class QueryBudget:
    max_rows: int = 200_000
    max_states: int = 50_000
    max_matches: int = 100
    timeout_ms: int = 2000

    def __post_init__(self) -> None:
        if min(self.max_rows, self.max_states, self.max_matches, self.timeout_ms) <= 0:
            raise ValueError("query budgets must be positive")


@dataclass
class QueryOutcome:
    matches: list[dict[str, Any]]
    complete: bool
    unknown: list[str]
    stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"matches": self.matches, "complete": self.complete,
                "unknown": self.unknown, "stats": self.stats}


class _Exhausted(Exception):
    pass


def _variable(term: str) -> bool:
    return term.startswith("$") or term == "@unit"


class QuotedTerm(str):
    """A KenQL JSON token, kept quoted so role analysis cannot capture it.

    Legacy patterns use shlex and retain their existing term semantics.
    """

    def __new__(cls, token: str):
        json.loads(token)  # Reject malformed escapes at parse time.
        return super().__new__(cls, token)

    @property
    def literal(self) -> str:
        return str(json.loads(self))


def _resolve(term: str, bindings: dict[str, str]) -> str | None:
    if isinstance(term, QuotedTerm):
        return term.literal
    if term == "_" or "|" in term:
        return None
    return bindings.get(term) if _variable(term) else term


def _bind(term: str, value: str, bindings: dict[str, str]) -> bool:
    if isinstance(term, QuotedTerm):
        return value == term.literal
    if term == "_":
        return True
    if _variable(term):
        if term in bindings:
            return bindings[term] == value
        bindings[term] = value
        return True
    return value in term.split("|")


@lru_cache(maxsize=256)
def _regex(pattern: str):
    import regex  # type: ignore[import-untyped]
    try:
        return regex.compile(pattern)
    except regex.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc


def _compare(actual: Any, op: str, expected: str) -> bool:
    if actual is None:
        return False
    if op in {">", "<", ">=", "<="}:
        try:
            a, b = float(actual), float(expected)
        except (ValueError, TypeError):
            return False
        return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    value = str(actual).lower() if isinstance(actual, bool) else str(actual)
    if op == "regex":
        try:
            return _regex(expected).search(value, timeout=0.01) is not None
        except TimeoutError as exc:
            raise _Exhausted("regex_timeout") from exc
    if op == "~=":
        return fnmatch.fnmatchcase(value, expected)
    equal = value in expected.split("|")
    return not equal if op == "!=" else equal


def evaluate_pattern(ir: IR | FactIndex, pattern: Pattern | str,
                     budget: QueryBudget | None = None) -> QueryOutcome:
    index = ir if isinstance(ir, FactIndex) else FactIndex(ir)
    from .selectors import parse_query
    p = parse_query(pattern) if isinstance(pattern, str) else pattern
    b = budget or QueryBudget()
    started = time.monotonic()
    stats: dict[str, Any] = {"rows_examined": 0, "states": 0, "path_edges": 0,
                             "relations": {r: len(v) for r, v in index.by_relation.items()}}
    unknown = sorted(p.capabilities - index.ir.capabilities)
    matches: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def tick(key: str, maximum: int) -> None:
        stats[key] += 1
        if stats[key] > maximum:
            raise _Exhausted(key)
        if (time.monotonic() - started) * 1000 >= b.timeout_ms:
            raise _Exhausted("timeout_ms")

    def candidates(c: Clause, bindings: dict[str, str]):
        subject, object = _resolve(c.subject, bindings), _resolve(c.object, bindings)
        if c.maximum == 1:
            yield from index.rows(c.relation, subject, object)
            return
        if c.attrs:
            raise ValueError("path clauses do not accept edge attributes")
        starts = [subject] if subject is not None else sorted({f.subject for f in index.rows(c.relation)})
        for start in starts:
            frontier: dict[str, list[str]] = {start: []}
            emitted: set[str] = set()
            for depth in range(1, c.maximum + 1):
                following: dict[str, list[str]] = {}
                for current, evidence in frontier.items():
                    for f in index.rows(c.relation, current):
                        tick("path_edges", b.max_rows)
                        following.setdefault(f.object, evidence + f.evidence)
                for target, evidence in following.items():
                    if depth >= c.minimum and target not in emitted and (object is None or object == target):
                        emitted.add(target)
                        yield Fact(start, c.relation, target, {"depth": depth}, evidence)
                frontier = following
                if not frontier:
                    break

    def rows(c: Clause, bindings: dict[str, str]):
        for f in candidates(c, bindings):
            tick("rows_examined", b.max_rows)
            result = dict(bindings)
            if not _bind(c.subject, f.subject, result) or not _bind(c.object, f.object, result):
                continue
            if all(_compare(f.attrs.get(k), op, v) for k, op, v in c.attrs):
                yield result, f

    def join(clauses: list[Clause], bindings: dict[str, str], evidence: list[Fact]):
        tick("states", b.max_states)
        if not clauses:
            yield bindings, evidence
            return
        # Re-plan at each binding; use endpoint cardinalities, not text order.
        c = min(clauses, key=lambda x: len(index.rows(x.relation,
                    _resolve(x.subject, bindings), _resolve(x.object, bindings))))
        remaining = list(clauses)
        remaining.remove(c)
        for result, f in rows(c, bindings):
            yield from join(remaining, result, evidence + [f])

    try:
        for variant, clauses in (p.variants or {"default": []}).items():
            all_clauses = p.clauses + clauses
            optional_total = sum(c.mode == "optional" for c in all_clauses)
            required = [c for c in all_clauses if c.mode == "require"]
            for bindings, evidence in join(required, {}, []):
                if any(bindings[a] == bindings[z] for a, z in p.different):
                    continue
                accepted = True
                missing = list(unknown)
                optional_hits = 0
                for c in (c for c in all_clauses if c.mode != "require"):
                    needed = c.capability
                    if c.mode == "forbid" and not needed:
                        needed = {"CALLS": "complete_type_resolution", "TARGET": "complete_type_resolution",
                                  "TYPE": "complete_type_resolution", "MAY_TARGET": "complete_type_resolution",
                                  "WAITS_FOR": "complete_concurrency_flow", "FLOWS_TO": "complete_dataflow"}.get(c.relation, "syntax")
                    if needed and needed not in index.ir.capabilities:
                        missing.append(needed)
                        continue
                    if c.mode == "count":
                        counts: set[Any] = set()
                        count_evidence: list[Fact] = []
                        for result, f in rows(c, bindings):
                            for enriched, facts in join(c.where, result, [f]):
                                if c.distinct and c.distinct not in enriched:
                                    raise ValueError(f"unbound count distinct role {c.distinct}")
                                key = enriched[c.distinct] if c.distinct else (f.subject, f.object)
                                counts.add(key)
                                count_evidence.extend(facts)
                        if not _compare(len(counts), c.count_op, str(c.count)):
                            accepted = False
                            break
                        evidence.extend(count_evidence)
                    else:
                        hit = next(rows(c, bindings), None)
                        if c.mode == "forbid" and hit:
                            accepted = False
                            break
                        if c.mode == "optional" and hit:
                            optional_hits += 1
                            evidence.append(hit[1])
                if not accepted:
                    continue
                key = (variant, *sorted(bindings.items()))
                if key in seen:
                    continue
                seen.add(key)
                if len(matches) >= b.max_matches:
                    raise _Exhausted("max_matches")
                matches.append({"pattern": p.name, "variant": variant,
                                "bindings": bindings, "status": "unknown" if missing else "structural_match",
                                "unknown": sorted(set(missing)), "optional_hits": optional_hits,
                                "optional_total": optional_total,
                                "evidence_score": round((len(required) + optional_hits) / (len(required) + optional_total), 3),
                                "evidence": sorted({e for f in evidence for e in f.evidence}),
                                "facts": [{"subject": f.subject, "relation": f.relation, "object": f.object}
                                          for f in evidence]})
    except _Exhausted as exc:
        unknown.append(f"budget:{exc}")
    matches.sort(key=lambda match: (-match["evidence_score"], str(sorted(match["bindings"].items()))))
    stats["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return QueryOutcome(matches, not unknown, sorted(set(unknown)), stats)
