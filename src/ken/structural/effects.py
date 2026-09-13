"""Language/API-specific effects and bug facts, separate from the neutral IR."""
from __future__ import annotations

import re
from collections import defaultdict

from .frontend import ASSIGNMENTS, FUNCTIONS, Lowerer, descendants, field
from .model import IR


def syntax_effects(lowerer: Lowerer) -> None:
    ir = lowerer.ir
    for node in descendants(lowerer.tree.root_node):
        owner = lowerer.owner[node.id]
        evidence = lowerer.evidence(node)
        kind = node.type
        def hazard(rule: str) -> None:
            event = lowerer.entity("HAZARD", f"{rule}:{node.start_byte}", owner, node)
            ir.add(event, "HAS_HAZARD", rule, evidence)
            ir.add(event, "OWNED_BY", owner, evidence)
        if ir.language == "python" and kind in {"default_parameter", "typed_default_parameter"}:
            value = field(node, "value")
            if value and value.type in {"list", "dictionary", "set"}:
                hazard("mutable-default-argument")
        if kind == "except_clause" and field(node, "value") is None and not any(c.type == "as_pattern" for c in node.named_children):
            # A typed except's exception may be an unnamed field in grammar versions.
            body = next((c for c in node.named_children if c.type == "block"), None)
            if body and len(node.named_children) == 1:
                hazard("bare-except")
        if kind in {"except_clause", "catch_clause"}:
            body = field(node, "body") or next((c for c in node.named_children if c.type in {"block", "statement_block"}), None)
            if body and all(c.type in {"pass_statement", "comment", "empty_statement"} for c in body.named_children):
                hazard("swallowed-exception")
        if kind in {"return_statement", "return_expression"} and lowerer.enclosing(node, {"finally_clause"}):
            hazard("return-in-finally")
        if kind in {"block", "statement_block", "compound_statement", "statement_list"}:
            terminated = False
            for child in node.named_children:
                if terminated and child.type not in {"comment", *FUNCTIONS}:
                    event = lowerer.entity("HAZARD", f"unreachable:{child.start_byte}", owner, child)
                    ir.add(event, "HAS_HAZARD", "unreachable-statement", lowerer.evidence(child))
                if child.type in {"return_statement", "return_expression", "throw_statement", "raise_statement", "break_statement", "continue_statement"}:
                    terminated = True
        if kind in ASSIGNMENTS:
            left, right = field(node, "left"), field(node, "right")
            if left and right and left.type == right.type == "identifier" and lowerer.text(left) == lowerer.text(right):
                hazard("self-assignment")
        if kind in {"binary_expression", "comparison_operator"}:
            op = lowerer.text(field(node, "operator")) or " ".join(c.type for c in node.children if not c.is_named)
            if ir.language in {"javascript", "typescript"} and op in {"==", "===", "!=", "!=="}:
                if any(lowerer.text(c) == "NaN" for c in node.named_children):
                    # A shadowed local NaN is excluded.
                    if not lowerer.resolve_name("NaN", owner):
                        hazard("nan-equality")
        if ir.language == "python" and kind == "assert_statement":
            expression = next(iter(node.named_children), None)
            if expression and expression.type == "tuple":
                hazard("tuple-assertion")
        if kind in {"go_statement"}:
            ir.add(owner, "SPAWNS_CONTEXT", f"{ir.path}::goroutine:{node.start_byte}", evidence, api="go")
        if kind in {"async_block", "async_expression"}:
            ir.add(owner, "HAS_ASYNC_SCOPE", f"{ir.path}::async:{node.start_byte}", evidence)
    ir.capabilities.add("syntax_hazards")


def concurrency_effects(graph: IR) -> None:
    """Recognize explicitly imported Python threading/asyncio API identities.

    A local rebinding invalidates the API model. Timed joins are MAY_WAIT_FOR;
    no happens-before edge is fabricated from source order alone.
    """
    aliases: dict[tuple[str, str], str] = {}
    for fact in graph.facts:
        if fact.relation != "IMPORT_SYNTAX" or fact.attrs["language"] != "python":
            continue
        path = fact.subject.removesuffix("::module")
        match = re.fullmatch(r"import\s+(threading|asyncio)(?:\s+as\s+(\w+))?", fact.object)
        if match:
            aliases[(path, match[2] or match[1])] = match[1]
        match = re.fullmatch(r"from\s+(threading|asyncio)\s+import\s+(.+)", fact.object)
        if match:
            for item in match[2].split(","):
                parts = re.split(r"\s+as\s+", item.strip())
                aliases[(path, parts[-1])] = f"{match[1]}.{parts[0]}"
    by_relation = defaultdict(list)
    for f in graph.facts:
        by_relation[f.relation].append(f)
    names = {f.subject: f.object for f in by_relation["CALLEE_NAME"]}
    receiver = {f.subject: f.object for f in by_relation["RECEIVER"]}
    args = defaultdict(list)
    for f in by_relation["ARGUMENT"]:
        args[f.subject].append(f)
    contexts: dict[str, set[str]] = defaultdict(set)
    rebound = {f.subject for f in by_relation["ASSIGNED_FROM"]}
    for call, name in names.items():
        entity = graph.entities[call]
        rec = receiver.get(call)
        rec_entity = graph.entities.get(rec or "")
        alias = rec_entity.name if rec_entity else name
        api = aliases.get((entity.path, alias), "")
        if not api:
            continue
        if rec in rebound or any(e.path == entity.path and e.name == alias and (e.kind in {"PARAMETER", "CALLABLE", "CLASS"} or e.id in rebound) for e in graph.entities.values()):
            continue
        if rec_entity:
            api += "." + name
        if api in {"threading.Thread", "threading.Lock", "threading.RLock", "asyncio.create_task"}:
            contexts[call].add(call)
            ev = f"{entity.path}:{entity.line}"
            effect = "CREATES_LOCK" if api.endswith((".Lock", ".RLock")) else "CREATES_CONTEXT"
            graph.add(call, effect, call, ev, api=api)
            if api == "asyncio.create_task":
                graph.add(call, "STARTS_CONTEXT", call, ev, api=api)
            for arg in args[call]:
                if arg.attrs.get("name") == "target" or api == "asyncio.create_task" and arg.attrs.get("position") == 0:
                    graph.add(call, "CONTEXT_ENTRY", arg.object, ev)
    for _ in range(16):
        changed = False
        for f in by_relation["ASSIGNED_FROM"]:
            before = len(contexts[f.subject])
            contexts[f.subject].update(contexts[f.object])
            changed |= len(contexts[f.subject]) != before
        if not changed:
            break
    for call, rec in receiver.items():
        for context in contexts[rec]:
            name = names[call]
            if name not in {"start", "join", "acquire", "release"}:
                continue
            creation = next((f for f in graph.facts if f.subject == context and f.relation in {"CREATES_LOCK", "CREATES_CONTEXT"}), None)
            if creation is None:
                continue
            if name in {"start", "join"} and creation.relation != "CREATES_CONTEXT":
                continue
            if name in {"acquire", "release"} and creation.relation != "CREATES_LOCK":
                continue
            effect = {"start": "STARTS_CONTEXT", "join": "WAITS_FOR", "acquire": "ACQUIRES_LOCK", "release": "RELEASES_LOCK"}[name]
            if len(contexts[rec]) != 1 or name == "join" and args[call]:
                effect = "MAY_" + effect
            entity = graph.entities[call]
            graph.add(call, effect, context, f"{entity.path}:{entity.line}")
    graph.capabilities.add("python_concurrency_api")


BUG_RULES = {
    "mutable-default-argument": ("A mutable literal default is shared between calls.", "warning"),
    "bare-except": ("An unqualified except also catches cancellation and termination exceptions.", "warning"),
    "swallowed-exception": ("The exception handler has no executable handling behavior.", "warning"),
    "return-in-finally": ("A finally return can suppress an exception or replace an earlier result.", "warning"),
    "unreachable-statement": ("A statement follows an unconditional terminator in the same block.", "warning"),
    "self-assignment": ("A local identifier is assigned to itself; check for a mistaken target.", "warning"),
    "nan-equality": ("Equality/inequality with the built-in NaN does not test numeric NaN state.", "warning"),
    "tuple-assertion": ("A nonempty tuple assertion is always truthy, regardless of its elements.", "warning"),
}


def evaluate_bugs(graph: IR, budget=None) -> dict:
    from .rules import builtin_rules, execute_rules, select_rules
    result = execute_rules(graph, select_rules(builtin_rules(), collections=["bugs"]), budget)
    findings = [{**m, "message": m["rule"]["description"], "severity": m["rule"]["severity"]}
                for m in result["matches"]]
    return {"findings": findings, "outcomes": result["outcomes"], "complete": result["complete"]}


def detect_bugs(graph: IR) -> list[dict]:
    """Convenience view; service callers use evaluate_bugs to retain budgets."""
    return evaluate_bugs(graph)["findings"]
