"""Scoped binding exploration; predicates never issue SQL queries."""

from __future__ import annotations

import math
import time
from collections import defaultdict

import numpy as np
import regex

from ..execution_control import ExecutionBudget, ExecutionStopped
from ..values import Unknown, identity, is_unknown
from .compiler import Calculate, Explore
from .tree import SyntaxValue, classification, contains_unknown, result_key


class Runtime:
    def __init__(self, cache, budget, coverage, *, reference=False, cancelled=None):
        self.cache, self.budget, self.reference = cache, budget, reference
        self.started = time.monotonic()
        self.deadline = (
            self.started + budget.timeout_ms / 1000
            if budget.timeout_ms is not None
            else math.inf
        )
        self.cancelled = cancelled
        self.states = self.scanned = self.unknown = 0
        self.patterns, self.kind_cache, self.counts = {}, {}, {}
        self.closed = coverage
        self.stats = defaultdict(lambda: {"candidates": 0, "matched": 0})

    def check(self):
        self.states += 1
        reason = (
            "cancelled"
            if self.cancelled and self.cancelled()
            else "timeout"
            if time.monotonic() >= self.deadline
            else "max_states"
            if self.budget.max_states is not None
            and self.states > self.budget.max_states
            else None
        )
        if reason:
            raise ExecutionStopped(reason)

    def regex(self, text, expression):
        if not isinstance(text, str):
            return Unknown("regex_input_unknown")
        self.check()
        if expression.value not in self.patterns:
            raw, flags = expression.value[1:].rsplit("/", 1)
            self.patterns[expression.value] = regex.compile(
                raw, sum({"i": regex.I, "m": regex.M, "s": regex.S}[f] for f in flags)
            )
        return (
            self.patterns[expression.value].search(
                text, timeout=max(0.000001, min(0.05, self.deadline - time.monotonic()))
            )
            is not None
        )

    def kinds(self, selector, exact):
        key = (selector, exact.get("kind"), exact.get("native_kind"))
        if key not in self.kind_cache:
            category = {"Expression": "expression", "Statement": "statement"}.get(
                selector, selector
            )
            result = set()
            for code, native in enumerate(self.cache.dictionary.words):
                kind, family = classification(native)
                if exact.get("native_kind") not in (None, native):
                    continue
                if category in ("expression", "statement") and category != family:
                    continue
                if exact.get("kind") not in (None, kind) and not (
                    exact.get("kind") == "compare" and kind == "binary"
                ):
                    continue
                result.add(code)
            self.kind_cache[key] = result
        return self.kind_cache[key]

    def estimate(self, instruction):
        kinds = frozenset(self.kinds(instruction.selector, instruction.exact))
        if not kinds:
            return 0
        if kinds not in self.counts:
            self.counts[kinds] = self.cache.db.execute(
                "SELECT coalesce(sum(length(nodes)/4),0) FROM postings p JOIN selected s ON p.unit=s.unit WHERE kind IN ("
                + ",".join("?" for _ in kinds)
                + ")",
                tuple(kinds),
            ).fetchone()[0]
        return self.counts[kinds]

    def related(self, role, value, hints, frame):
        for left, right, direct in hints:
            if role == right and left in frame:
                a, b = frame[left], value
            elif role == left and right in frame:
                a, b = value, frame[right]
            else:
                continue
            if (
                not isinstance(a, SyntaxValue)
                or not isinstance(b, SyntaxValue)
                or a.unit != b.unit
            ):
                return False
            if direct:
                if b.tree.parent[b.index] != a.index:
                    return False
            elif not a.index < b.index < a.tree.end[a.index]:
                return False
        return True

    def scan(self, role, selector, exact, owner, hints, frame):
        kinds = self.kinds(selector, exact)
        bound = frame.get(role)
        parent = frame.get(owner) if owner else None
        anchor = parent
        reverse = False
        direct = bool(owner)
        if bound is not None:
            sources = (
                [(bound.tree, [bound.index])] if isinstance(bound, SyntaxValue) else []
            )
        else:
            for left, right, immediate in hints:
                if anchor is not None:
                    break
                if role == right and isinstance(frame.get(left), SyntaxValue):
                    anchor, direct = frame[left], immediate
                elif role == left and isinstance(frame.get(right), SyntaxValue):
                    anchor, reverse, direct = frame[right], True, immediate
            if anchor is not None and not self.reference:
                tree = anchor.tree
                if reverse:
                    ancestors, current = [], int(tree.parent[anchor.index])
                    while current >= 0:
                        self.check()
                        ancestors.append(current)
                        if direct:
                            break
                        current = int(tree.parent[current])
                    sources = [(tree, reversed(ancestors))]
                else:
                    posting = tree.positions(kinds)
                    lo = int(np.searchsorted(posting, anchor.index + 1))
                    hi = int(np.searchsorted(posting, int(tree.end[anchor.index])))
                    ids = posting[lo:hi]
                    if direct:
                        ids = ids[tree.parent[ids] == anchor.index]
                    sources = [(tree, ids)]
            else:

                def roots():
                    for unit, ids in self.cache.candidates(
                        None if self.reference else kinds
                    ):
                        self.check()
                        path, language, _, _ = self.cache.units[unit]
                        if exact.get("path") not in (None, path) or exact.get(
                            "language"
                        ) not in (None, language):
                            continue
                        yield self.cache.view(unit), ids

                sources = roots()
        for tree, candidates in sources:
            for ident in candidates:
                self.check()
                ident = int(ident)
                if ident < 0 or ident >= len(tree.kind):
                    raise ValueError("corrupt syntax posting node ID")
                self.scanned += 1
                self.stats[role]["candidates"] += 1
                if tree.kind[ident] not in kinds:
                    continue
                value = tree.value(ident)
                if parent is not None and (
                    tree.unit != parent.unit or tree.parent[ident] != parent.index
                ):
                    continue
                if not self.related(role, value, hints, frame):
                    continue
                if any(
                    not is_unknown(actual := value.get(key))
                    and identity(actual) != identity(expected)
                    for key, expected in exact.items()
                ):
                    continue
                self.stats[role]["matched"] += 1
                yield value

    def domain_closed(self, parameters, hints, frame):
        if self.closed:
            return True
        # A valid enclosing subtree is closed even when another file was skipped.
        # Only positive containment constraints can establish this boundary.
        closed = {
            role
            for role, value in frame.items()
            if isinstance(value, SyntaxValue) and not value.tree.flags[value.index] & 6
        }
        for _ in parameters:
            for left, right, _direct in hints:
                if left in closed:
                    closed.add(right)
        return all(p.role in closed for p in parameters)


def scheduled(plan, runtime):
    """Order each conjunctive scan group, preserving calculation barriers."""
    result, group, bound = [], [], set()

    def flush():
        while group:
            available = [s for s in group if s.owner is None or s.owner in bound]

            def score(scan):
                linked = scan.owner in bound or any(
                    (scan.role == a and b in bound) or (scan.role == b and a in bound)
                    for a, b, _ in plan.relations
                )
                return (0 if linked else 1, runtime.estimate(scan))

            step = available[0] if runtime.reference else min(available, key=score)
            group.remove(step)
            result.append(step)
            bound.add(step.role)

    for instruction in plan.instructions:
        if isinstance(instruction, Explore):
            if any(test.regex is not None for test in instruction.tests):
                flush()
                result.append(instruction)
                bound.add(instruction.role)
                continue
            group.append(instruction)
        else:
            flush()
            result.append(instruction)
            if instruction.role:
                bound.add(instruction.role)
    flush()
    return result


def frames(plan, runtime, schedule):
    """A stack of independent iterators resets bindings at every scope exit."""

    def apply(step, frame, uncertain):
        runtime.check()
        if isinstance(step, Calculate):
            value = step.evaluate(frame, runtime)
            if step.role:
                yield {**frame, step.role: value}, uncertain
            elif value is not False:
                yield frame, uncertain or is_unknown(value)
            return
        for node in runtime.scan(
            step.role, step.selector, step.exact, step.owner, plan.relations, frame
        ):
            unknown = uncertain or bool(node.tree.flags[node.index] & 6)
            unknown |= any(is_unknown(node.get(key)) for key in step.exact)
            valid = True
            for test in step.tests:
                if test.regex is not None:
                    truth = runtime.regex(node.get(test.name), test.regex)
                    unknown |= is_unknown(truth)
                    if truth is False:
                        valid = False
                        break
            if valid:
                yield {**frame, step.role: node}, unknown

    stack = [iter([({}, False)])]
    try:
        while stack:
            runtime.check()
            try:
                frame, uncertain = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            if len(stack) > len(schedule):
                yield frame, uncertain
            else:
                stack.append(iter(apply(schedule[len(stack) - 1], frame, uncertain)))
    finally:
        for iterator in stack:
            if hasattr(iterator, "close"):
                iterator.close()


def serialize(value):
    if isinstance(value, SyntaxValue):
        return value.record()
    if isinstance(value, tuple):
        return [serialize(v) for v in value]
    return value


def execute(
    plan,
    cache,
    *,
    coverage=True,
    timeout_ms=None,
    max_states=None,
    max_rows=None,
    reference=False,
    cancelled=None,
    profile=False,
):
    runtime = Runtime(
        cache,
        ExecutionBudget(timeout_ms, max_states, max_rows),
        coverage,
        reference=reference,
        cancelled=cancelled,
    )
    rows, seen, physical = [], set(), []
    complete, reason, truncated = True, None, False
    try:
        for branch in plan.branches or (plan,):
            schedule = scheduled(branch, runtime)
            physical.append(
                [
                    {
                        "operator": "explore"
                        if isinstance(s, Explore)
                        else "calculate",
                        "role": s.role,
                        **(
                            {"selector": s.selector, "owner": s.owner, "seed": s.exact}
                            if isinstance(s, Explore)
                            else {}
                        ),
                    }
                    for s in schedule
                ]
            )
            stream = frames(branch, runtime, schedule)
            try:
                for frame, uncertain in stream:
                    projected = tuple(f(frame, runtime) for f in branch.projection)
                    ordered = tuple(f(frame, runtime) for f in branch.ordering)
                    if uncertain or any(
                        contains_unknown(v) for v in projected + ordered
                    ):
                        runtime.unknown += 1
                        continue
                    # Detach results from owning trees; returning a node must not
                    # retain every file buffer until the end of the whole query.
                    key = tuple(result_key(v) for v in projected)
                    if key in seen:
                        continue
                    if max_rows is not None and len(rows) >= max_rows:
                        raise ExecutionStopped("max_rows")
                    seen.add(key)
                    rows.append(([serialize(v) for v in projected], ordered))
            finally:
                stream.close()
        for position in reversed(range(len(plan.program.ordering))):
            rows.sort(
                key=lambda row: row[1][position],
                reverse=plan.program.ordering[position].value == "desc",
            )
        if plan.program.limit is not None:
            truncated = len(rows) > plan.program.limit
            rows = rows[: plan.program.limit]
    except ExecutionStopped as exc:
        complete, reason = False, str(exc)
    except TimeoutError:
        complete, reason = False, "regex_timeout"
    except (ValueError, ArithmeticError, RecursionError) as exc:
        complete, reason = False, str(exc)
    return {
        "rows": [row for row, _ in rows],
        "complete": complete,
        "reason": reason,
        "unknown_candidates": runtime.unknown,
        "results_truncated": truncated,
        "plan": physical,
        "optional_evidence": [],
        "metrics": {
            "states": runtime.states,
            "scanned_nodes": runtime.scanned,
            "query_ms": (time.monotonic() - runtime.started) * 1000,
            **({"operator_profile": dict(runtime.stats)} if profile else {}),
        },
    }
