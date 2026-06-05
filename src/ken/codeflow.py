"""Call graph, wiring, and type hierarchy over the live worktree.

Built on ``ken.structure`` (tree-sitter extraction) + the indexed symbol
table. Resolution is **precision-first and tier-labelled** — we never argmax
an ambiguous name into a confident edge:

* **T1** — callee defined in the same file, or a name unique in the repo.
* **T2** — the name resolves to a single file that the caller imports.
* **T3** — ambiguous; reported as an unresolved call-site, not an edge.

Python only for now (see ``ken.structure.SUPPORTED``); other languages return
an explicit ``unsupported`` note instead of a wrong answer.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ken import structure


def _py_files(conn) -> list[tuple[int, str]]:
    return [(int(r["id"]), r["path"]) for r in conn.execute(
        "SELECT id, path FROM ci_files WHERE language = 'python'")]


def _name_defs(conn) -> dict[str, list[dict]]:
    defs: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        """
        SELECT s.id, s.name, s.qualname, s.kind, s.line_start, s.line_end,
               s.file_id, f.path
        FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
        WHERE f.language = 'python'
        """
    ):
        defs[r["name"]].append({
            "symbol_id": int(r["id"]), "name": r["name"], "qualname": r["qualname"],
            "kind": r["kind"], "line_start": int(r["line_start"]),
            "line_end": int(r["line_end"]), "file_id": int(r["file_id"]), "path": r["path"],
        })
    return defs


def _file_imports(conn) -> dict[int, set[int]]:
    imports: dict[int, set[int]] = defaultdict(set)
    for r in conn.execute(
        "SELECT from_file_id, to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL"
    ):
        imports[int(r["from_file_id"])].add(int(r["to_file_id"]))
    return imports


def _symbols_by_file(conn) -> dict[str, list[dict]]:
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        """
        SELECT s.name, s.qualname, s.line_start, s.line_end, f.path
        FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
        WHERE f.language = 'python'
        """
    ):
        by_file[r["path"]].append({
            "qualname": r["qualname"] or r["name"],
            "line_start": int(r["line_start"]), "line_end": int(r["line_end"]),
        })
    return by_file


def _enclosing(by_file: dict[str, list[dict]], path: str, line: int) -> str:
    best = None
    for s in by_file.get(path, ()):
        if s["line_start"] <= line <= s["line_end"]:
            span = s["line_end"] - s["line_start"]
            if best is None or span < best[0]:
                best = (span, s["qualname"])
    return best[1] if best else "<module>"


def _resolve(name, caller_fid, defs, imports):
    """Return (candidate_dict, tier) or (None, 'T3')."""
    cands = defs.get(name, [])
    if not cands:
        return None, "T3"
    same = [c for c in cands if c["file_id"] == caller_fid]
    if len(same) == 1:
        return same[0], "T1"
    if len(cands) == 1:
        return cands[0], "T1"
    imported = [c for c in cands if c["file_id"] in imports.get(caller_fid, set())]
    if len(imported) == 1:
        return imported[0], "T2"
    return None, "T3"


def _read_bytes(project_root: Path, rel: str) -> bytes:
    try:
        return (project_root.resolve() / rel).read_bytes()
    except OSError:
        return b""


def _tier_ok(tier: str, min_conf: str) -> bool:
    order = {"T1": 1, "T2": 2, "T3": 3}
    return order.get(tier, 3) <= order.get(min_conf, 2)


def callgraph(
    conn,
    qualname: str,
    *,
    path: str | None = None,
    direction: str = "both",
    min_confidence: str = "T2",
    limit: int = 50,
    project_root: Path | None = None,
) -> dict:
    """Who calls *qualname*, and what it calls (precision-tiered)."""
    if project_root is None:
        return {"ok": False, "error": "project_root required"}
    defs = _name_defs(conn)
    imports = _file_imports(conn)
    by_file = _symbols_by_file(conn)

    # Locate the target symbol.
    target = None
    for c in defs.get(qualname.rsplit(".", 1)[-1], []):
        if c["qualname"] == qualname or c["name"] == qualname:
            if path is None or c["path"] == Path(path).as_posix().lstrip("./"):
                target = c
                break
    if target is None:
        return {"ok": False, "error": "symbol not found (python only)", "qualname": qualname}

    out: dict = {"ok": True, "qualname": target["qualname"], "file": target["path"],
                 "min_confidence": min_confidence}

    if direction in ("callees", "both"):
        src = _read_bytes(project_root, target["path"])
        edges, unresolved = [], []
        seen = set()
        for call in structure.extract_calls(src, "python"):
            if not (target["line_start"] <= call.line <= target["line_end"]):
                continue
            cand, tier = _resolve(call.name, target["file_id"], defs, imports)
            if cand is None:
                unresolved.append({"name": call.name, "line": call.line})
                continue
            key = (cand["symbol_id"], call.line)
            if key in seen or not _tier_ok(tier, min_confidence):
                continue
            seen.add(key)
            edges.append({"to_qualname": cand["qualname"], "file": cand["path"],
                          "line": call.line, "confidence_tier": tier})
        out["callees"] = edges[: max(1, int(limit))]
        out["unresolved_callsites"] = unresolved[:limit]

    if direction in ("callers", "both"):
        callers = []
        for fid, fpath in _py_files(conn):
            src = _read_bytes(project_root, fpath)
            if target["name"].encode() not in src:
                continue
            for call in structure.extract_calls(src, "python"):
                if call.name != target["name"]:
                    continue
                cand, tier = _resolve(call.name, fid, defs, imports)
                if cand is None or cand["symbol_id"] != target["symbol_id"]:
                    continue
                if not _tier_ok(tier, min_confidence):
                    continue
                callers.append({
                    "from_qualname": _enclosing(by_file, fpath, call.line),
                    "file": fpath, "line": call.line, "confidence_tier": tier,
                })
        out["callers"] = callers[: max(1, int(limit))]

    return out


def wiring(
    conn,
    *,
    query: str | None = None,
    trigger_kind: str | None = None,
    limit: int = 50,
    project_root: Path | None = None,
) -> dict:
    """Routes / CLI / env-var triggers and their handler symbols."""
    if project_root is None:
        return {"ok": False, "error": "project_root required"}
    by_file = _symbols_by_file(conn)
    rows = []
    for _fid, fpath in _py_files(conn):
        src = _read_bytes(project_root, fpath)
        for w in structure.extract_wiring(src, "python"):
            if trigger_kind and w.kind != trigger_kind:
                continue
            if query and query.lower() not in (w.trigger + " " + w.decorator).lower():
                continue
            rows.append({
                "kind": w.kind, "trigger": w.trigger, "decorator": w.decorator,
                "handler_qualname": _enclosing(by_file, fpath, w.line),
                "file": fpath, "line": w.line,
            })
    rows.sort(key=lambda r: (r["kind"], r["file"], r["line"]))
    return {"ok": True, "count": len(rows), "wiring": rows[: max(1, int(limit))]}


def type_hierarchy(
    conn,
    qualname: str,
    *,
    direction: str = "sub",
    with_overrides: bool = True,
    project_root: Path | None = None,
) -> dict:
    """Subclasses / ancestors of a class, plus override detection."""
    if project_root is None:
        return {"ok": False, "error": "project_root required"}

    all_classes: dict[str, list[dict]] = defaultdict(list)
    methods_by_class: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute(
        """
        SELECT s.name, s.qualname, s.kind, f.path
        FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
        WHERE f.language = 'python'
        """
    ):
        if r["kind"] == "class":
            all_classes[r["name"]].append({"name": r["name"], "qualname": r["qualname"],
                                           "path": r["path"]})
        elif r["kind"] == "method" and r["qualname"]:
            cls = r["qualname"].rsplit(".", 1)[0]
            methods_by_class[cls].add(r["name"])

    # child class name -> [base names], from live extraction
    child_to_bases: dict[str, list[str]] = {}
    for _fid, fpath in _py_files(conn):
        src = _read_bytes(project_root, fpath)
        for cb in structure.extract_bases(src, "python"):
            child_to_bases[cb.name] = cb.bases

    target_name = qualname.rsplit(".", 1)[-1]
    if target_name not in all_classes:
        return {"ok": False, "error": "class not found (python only)", "qualname": qualname}

    if direction == "super":
        ancestors: list[str] = []
        seen = set()
        frontier = list(child_to_bases.get(target_name, []))
        while frontier:
            b = frontier.pop()
            if b in seen:
                continue
            seen.add(b)
            ancestors.append(b)
            frontier.extend(child_to_bases.get(b, []))
        result = ancestors
    else:
        # subclasses: transitive closure over reverse base edges
        rev: dict[str, list[str]] = defaultdict(list)
        for child, bases in child_to_bases.items():
            for b in bases:
                rev[b].append(child)
        descendants: list[str] = []
        seen = set()
        frontier = list(rev.get(target_name, []))
        while frontier:
            c = frontier.pop()
            if c in seen:
                continue
            seen.add(c)
            descendants.append(c)
            frontier.extend(rev.get(c, []))
        result = descendants

    out = {"ok": True, "qualname": qualname, "direction": direction,
           ("ancestors" if direction == "super" else "descendants"): sorted(result)}

    if with_overrides and direction == "sub":
        # a subclass "overrides" a target method when it redefines the same name
        overrides = []
        target_methods = methods_by_class.get(target_name, set())
        for sub in result:
            # find target class methods that the subclass redefines
            sub_methods = methods_by_class.get(sub, set())
            shared = sorted(sub_methods & target_methods)
            if shared:
                overrides.append({"class": sub, "overrides": shared, "confidence": "best-effort"})
        out["overrides"] = overrides
    return out
