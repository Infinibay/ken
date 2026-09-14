"""Saved graph queries with optional metadata; categories never affect execution."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ken._paths import resolve_project_path
from .model import FactIndex, IR
from .query import QueryOutcome
from .query import QueryBudget, evaluate_pattern
from .selectors import parse_query


def _parsed_query(source: str, parsed: dict[str, Any]):
    """Compile once within one request; never share mutable ASTs across requests."""
    from .kenql import parse
    if source not in parsed:
        parsed[source] = parse(source)
    return parsed[source]


@dataclass
class SavedRule:
    id: str
    query: str
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    severity: str | None = None
    recommendation: str = ""
    caveat: str = ""
    variants: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    operations: list[dict[str, str]] = field(default_factory=list)

    def validate(self) -> None:
        self._validate({})

    def _validate(self, parsed: dict[str, Any]) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*(?:#[a-zA-Z0-9_.-]+)?", self.id):
            raise ValueError("rule id must contain only letters, numbers, dots, underscores or hyphens")
        for key in ("query", "name", "description", "recommendation", "caveat", "source"):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f"rule {self.id}: {key} must be a string")
        for key in ("tags", "collections"):
            values = getattr(self, key)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"rule {self.id}: {key} must be a list of nonempty strings")
        if not isinstance(self.variants, list) or any(not isinstance(v, dict) for v in self.variants):
            raise ValueError("variants must be a list of objects")
        variant_ids = set()
        for variant in self.variants:
            vid = variant.get("id")
            if not isinstance(vid, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", vid) or vid in variant_ids:
                raise ValueError("invalid or duplicate variant id")
            variant_ids.add(vid)
            if variant.get("status") == "ready":
                if not isinstance(variant.get("query"), str): raise ValueError("ready variant requires a query")
                _parsed_query(variant["query"], parsed)
        if not isinstance(self.operations, list):
            raise ValueError('operations must be a list')
        operation_ids = set()
        for operation in self.operations:
            if not isinstance(operation, dict) or set(operation) - {'id','status','query','description','caveat'} or any(not isinstance(v,str) for v in operation.values()):
                raise ValueError('invalid operation fields')
            oid = operation.get('id','')
            if not re.fullmatch(r'[a-zA-Z_][\w-]*', oid) or oid in operation_ids:
                raise ValueError('invalid or duplicate operation id')
            operation_ids.add(oid)
            if operation.get('status') not in {'ready','design'}:
                raise ValueError('operation status must be ready or design')
            if operation['status'] == 'ready':
                _parsed_query(operation.get('query',''), parsed)
        if self.severity is not None and not isinstance(self.severity, str):
            raise ValueError(f"rule {self.id}: severity must be a string or null")
        if self.query.lstrip().startswith("query "):
            _parsed_query(self.query, parsed)
        else:
            parse_query(self.query)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def builtin_rules() -> list[SavedRule]:
    from importlib.resources import files
    import tomllib
    from .catalog import _load_catalog
    RULES = _load_catalog()
    from .effects import BUG_RULES
    modern = []
    for path in sorted(files("ken.structural").joinpath("modern_patterns").iterdir(), key=lambda p: p.name):
        if path.name.endswith(".toml"):
            rule = SavedRule(**tomllib.loads(path.read_text(encoding="utf-8")), source=str(path))
            rule.validate()
            modern.append(rule)
    return [SavedRule(r.id, r.query, r.name, r.description,
                      tags=["design", r.category], collections=["gof"], caveat=r.caveat, variants=r.variants, source=r.source, operations=r.operations) for r in RULES] + [
        SavedRule(id, f"require $unit HAS_HAZARD {id}", name=id, description=message,
                  tags=["correctness"], collections=["bugs"], severity=severity)
        for id, (message, severity) in BUG_RULES.items()] + modern


def read_rules(path: Path) -> list[SavedRule]:
    try:
        if path.suffix == ".toml":
            import tomllib
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if "id" in data:
                data = {"version": 1, "rules": [data]}
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load rules from {path}: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1 or not isinstance(data.get("rules"), list):
        raise ValueError(f"{path}: expected version 1 and a rules array")
    rules = []
    seen = set()
    for item in data["rules"]:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: each rule must be an object")
        try:
            rule = SavedRule(**item)
        except TypeError as exc:
            raise ValueError(f"{path}: invalid rule fields: {exc}") from exc
        rule.validate()
        if rule.id in seen:
            raise ValueError(f"duplicate rule id: {rule.id}")
        seen.add(rule.id)
        rules.append(rule)
    return rules


def load_rules(root: Path, files: list[str] | None = None) -> list[SavedRule]:
    result = builtin_rules()
    paths = []
    local = resolve_project_path(root, ".ken/rules.json")
    if local.exists():
        paths.append(local)
    directory = resolve_project_path(root, ".ken/rules")
    if directory.is_dir():
        paths.extend(resolve_project_path(root, p.relative_to(root)) for p in sorted(directory.glob("*.toml")))
    for name in files or []:
        path = resolve_project_path(root, name)
        if path not in paths:
            paths.append(path)
    seen = {"legacy.gof." + r.id for r in result if "gof" in r.collections} | {r.id for r in result} | {"gof." + r.id for r in result if "gof" in r.collections} | {prefix + r.id + "#" + v["id"] for r in result for v in r.variants for prefix in ("", "gof.")}
    for path in paths:
        for rule in read_rules(path):
            if rule.id in seen:
                raise ValueError(f"duplicate rule id: {rule.id}; use a distinct id instead of shadowing a rule")
            result.append(rule)
            seen.add(rule.id)
    return result


def select_rules(rules: list[SavedRule], ids: list[str] | None = None,
                 collections: list[str] | None = None, tags: list[str] | None = None) -> list[SavedRule]:
    """OR inside each selector, intersection across selector types."""
    for label, requested, known in [
        ("rule", ids, {r.id for r in rules}),
        ("collection", collections, {c for r in rules for c in r.collections}),
        ("tag", tags, {t for r in rules for t in r.tags}),
    ]:
        unknown = set(requested or []) - known
        if unknown:
            raise ValueError(f"unknown {label}: {', '.join(sorted(unknown))}")
    return [r for r in rules if (not ids or r.id in ids)
            and (not collections or set(r.collections) & set(collections))
            and (not tags or set(r.tags) & set(tags))]


def save_rule(root: Path, rule: SavedRule, *, overwrite: bool = False) -> Path:
    """Save one visible TOML file, serializing read/check/replace under a lock."""
    import fcntl
    rule.validate()
    path = resolve_project_path(root, f".ken/rules/{rule.id}.toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".write.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = {r.id: r for r in load_rules(root)}
        if rule.id in existing and (not overwrite or existing[rule.id].source):
            raise ValueError(f"rule {rule.id} already exists; built-in ids are reserved; use --overwrite for a custom file")
        if rule.id in existing and not path.exists():
            raise ValueError("rule is defined in another library; edit its source file instead")
        query_registry([r for id, r in existing.items() if id != rule.id] + [rule])
        values = rule.to_dict()
        # TOML has no null. Absent optional metadata gets dataclass defaults.
        values.pop('variants'); values.pop('source')
        operations = values.pop('operations')
        content = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items() if v is not None) + "\n"
        for operation in operations:
            content += '\n[[operations]]\n' + '\n'.join(f'{k} = {json.dumps(v, ensure_ascii=False)}' for k,v in operation.items()) + '\n'
        fd, temporary = tempfile.mkstemp(prefix="rules-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return path


def query_registry(rules: list[SavedRule], *, _parsed: dict[str, Any] | None = None):
    from .kenql import legacy_query, Query, Node
    compiled = {} if _parsed is None else _parsed
    queries = {}
    from .catalog import RULES
    historical = {r.id: r for r in RULES if r.legacy_query}
    for item in rules:
        item._validate(compiled)
        old = historical.get(item.id)
        if old and item.source == old.source:
            queries["legacy.gof." + item.id] = legacy_query(old.legacy_query, item.id)
        queries[item.id] = _parsed_query(item.query, compiled) if item.query.lstrip().startswith("query ") else legacy_query(item.query, item.id)
        if "gof" in item.collections:
            queries["gof." + item.id] = queries[item.id]
        for variant in item.variants:
            if variant.get("status") == "ready":
                q = _parsed_query(variant["query"], compiled)
                queries[item.id + "#" + variant["id"]] = q
                if "gof" in item.collections:
                    queries["gof." + item.id + "#" + variant["id"]] = q
    for item in rules:
        for operation in item.operations:
            if operation['status'] != 'ready':
                continue
            name = item.id + '.' + operation['id']
            if name in queries:
                raise ValueError(f'duplicate named query: {name}')
            queries[name] = _parsed_query(operation['query'], compiled)
    for item in rules:
        if "gof" not in item.collections:
            continue
        ready = [v for v in item.variants if v.get("status") == "ready"]
        if ready:
            common = set.intersection(*(set(_parsed_query(v["query"], compiled).exports) for v in ready))
            if not common:
                raise ValueError(f"rule {item.id}: ready variants need common exported roles")
            exports = {role: "$" + role for role in sorted(common)}
            branches = [[Node("match", (item.id + "#" + v["id"], exports, ""))] for v in ready]
            # The canonical relation unites variants with a compatible public interface.
            queries["gof." + item.id] = Query("gof." + item.id, [Node("any", children=branches)], exports)
    return queries


def named_rule(rule_id: str, registry: list[SavedRule]) -> SavedRule:
    """Turn a named relation (including a variant) into a normal public query."""
    queries = query_registry(registry)
    if rule_id not in queries:
        raise ValueError(f"unknown or unavailable named query: {rule_id}")
    roles = queries[rule_id].exports
    bindings = ", ".join(f"{role}: ${role}" for role in roles)
    projection = ", ".join(f"${role}" for role in roles)
    query = f'query selected {{ match {json.dumps(rule_id)}({bindings}); emit {projection}; }}'
    return SavedRule(rule_id, query, name=rule_id)


# Bumped when the engine's own semantics change. The rule text is the version of
# a query -- editing it, or promoting a variant from design to ready, changes the
# fingerprint -- but a planner or evidence-mode change is invisible to the text,
# so it gets its own number.
QUERY_CACHE_VERSION = "1"


def rule_fingerprint(rule: SavedRule, evidence_mode: str, *, queries: dict[str, Any] | None = None,
                     root: Any = None, registry: list[SavedRule] | None = None) -> str:
    """Everything that can change what a rule returns, as one string.

    A rule's own text is not enough: a query that ``match``es a saved rule
    inherits that rule's meaning, and editing the saved file changes the answer
    without touching the caller. The reachable named queries are walked and their
    text and exported roles folded in, so a cache entry can only be read when the
    whole dependency closure is the same one.
    """
    parts = ["rule", QUERY_CACHE_VERSION, evidence_mode, rule.id, rule.query]
    for variant in sorted(rule.variants or [], key=lambda item: str(item.get("id", ""))):
        parts += [str(variant.get("id", "")), str(variant.get("status", "")),
                  str(variant.get("query", ""))]
    if queries and root is not None:
        by_id = {saved.id: saved for saved in (registry or [])}
        seen: set[str] = set()
        stack = [name for name, _ in root.dependencies()]
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            parts.append(name)
            saved = by_id.get(name)
            if saved is not None:
                parts.append(saved.query)
            child = queries.get(name)
            if child is not None:
                parts.append(json.dumps(child.exports, sort_keys=True))
                stack.extend(dependency for dependency, _ in child.dependencies())
    return "\x00".join(parts)


def execute_rules(ir: IR | FactIndex, rules: list[SavedRule], budget: QueryBudget | None = None, registry: list[SavedRule] | None = None, evidence_mode: str = "strict", *, _parsed: dict[str, Any] | None = None, cache: Any = None, graph_key: str = "") -> dict[str, Any]:
    # Validate the entire batch before evaluating any member.
    parsed = []
    compiled = {} if _parsed is None else _parsed
    for rule in rules:
        rule._validate(compiled)
        if rule.query.lstrip().startswith("query "):
            pattern = None
        else:
            pattern = parse_query(rule.query)
        if pattern is not None:
            pattern.name = rule.name or rule.id
        parsed.append((rule, pattern))
    index = ir if isinstance(ir, FactIndex) else FactIndex(ir)
    modern_index = None
    queries = {}
    if any(pattern is None for _, pattern in parsed):
        from .kenql import query_graph
        modern_index = query_graph(index.ir)
        queries = query_registry(registry or rules, _parsed=compiled)
    matches = []
    outcomes = {}
    for rule, pattern in parsed:
        # A stored outcome is keyed by the rule's text, the graph it ran on and
        # the engine version, so a changed query or a changed file can only miss.
        cache_key = ""
        if cache is not None and graph_key:
            compiled_query = _parsed_query(rule.query, compiled) if pattern is None else None
            cache_key = cache.key(rule_fingerprint(rule, evidence_mode, queries=queries,
                                                  root=compiled_query, registry=registry or rules), graph_key)
            stored = cache.get(cache_key)
            if stored is not None:
                outcome = QueryOutcome(**stored)
                outcomes[rule.id] = {"complete": outcome.complete, "unknown": outcome.unknown, "stats": outcome.stats}
                for match in outcome.matches:
                    locations = sorted({(index.ir.entities[v].path, index.ir.entities[v].line)
                                        for v in match["bindings"].values() if v in index.ir.entities})
                    unit = index.ir.entities.get(match["bindings"].get("$unit", ""))
                    primary = (unit.path, unit.line) if unit else (locations[0] if locations else ("", 0))
                    matches.append({**match, "id": rule.id, "rule": rule.to_dict(),
                                    "path": primary[0], "line": primary[1], "symbol": unit.name if unit else "",
                                    "locations": [{"path": p, "line": line} for p, line in locations]})
                continue
        if pattern is None:
            from .kenql import Engine
            assert modern_index is not None
            outcome = QueryOutcome(**Engine(modern_index, queries, budget, evidence_mode).execute(_parsed_query(rule.query, compiled)))
        else:
            outcome = evaluate_pattern(index, pattern, budget)
        if cache_key:
            cache.put(cache_key, outcome.to_dict())
        outcomes[rule.id] = {"complete": outcome.complete, "unknown": outcome.unknown, "stats": outcome.stats}
        for match in outcome.matches:
            locations = sorted({(index.ir.entities[v].path, index.ir.entities[v].line)
                                for v in match["bindings"].values() if v in index.ir.entities})
            unit = index.ir.entities.get(match["bindings"].get("$unit", ""))
            primary = (unit.path, unit.line) if unit else (locations[0] if locations else ("", 0))
            matches.append({**match, "id": rule.id, "rule": rule.to_dict(),
                            "path": primary[0], "line": primary[1], "symbol": unit.name if unit else "",
                            "locations": [{"path": p, "line": line} for p, line in locations]})
    return {"matches": matches, "outcomes": outcomes, "complete": all(o["complete"] for o in outcomes.values())}
