"""Find explicit Python access spellings, keeping runtime obligations separate."""

import ast
from pathlib import Path

from ken._paths import resolve_project_path
from ken.structural.python_imports import targets
from .graph import Program, location, qualname


def describe(root: Path, program: Program, seeds: list[str], context: str) -> dict:
    path = resolve_project_path(root, context).relative_to(root.resolve()).as_posix()
    candidates = []
    issues = []
    if not path.endswith(".py"):
        return {
            "status": "unknown",
            "context": path,
            "candidates": [],
            "reason": "Contextual access expressions are currently modeled for Python; no cross-language visibility claim.",
        }
    try:
        with (root / path).open("rb") as handle:
            source = handle.read(2_000_001)
        if len(source) > 2_000_000:
            raise ValueError("context source budget exhausted")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError) as exc:
        return {
            "status": "unknown",
            "context": path,
            "candidates": [],
            "reason": str(exc),
        }
    paths = {p for p, _ in (program.snapshot or {}).get("manifest", [])}
    for key in seeds:
        node = program.nodes[key]
        name = qualname(node)
        if "." in name:
            issues.append(
                "Methods require an instance/type and initialization analysis."
            )
            continue
        expressions: list[dict] = []
        if node["path"] == path:
            expressions.append({"expression": name, "basis": "same_module_declaration"})
        # Only module-level imports are witnesses for module-level availability.
        # Nested/conditional imports are retained as an unresolved obligation.
        for item in tree.body:
            if isinstance(item, ast.ImportFrom):
                module = "." * item.level + (item.module or "")
                found = targets(path, module, paths)
                if found == [node["path"]]:
                    expressions.extend(
                        {
                            "expression": a.asname or a.name,
                            "basis": "explicit_from_import",
                            "line": item.lineno,
                        }
                        for a in item.names
                        if a.name == name
                    )
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    if targets(path, alias.name, paths) == [node["path"]]:
                        expressions.append(
                            {
                                "expression": (alias.asname or alias.name) + "." + name,
                                "basis": "explicit_module_import",
                                "line": item.lineno,
                            }
                        )
        for expression in expressions:
            candidates.append(
                {
                    "target": location(node),
                    **expression,
                    "status": "candidate",
                    "obligations": [
                        "binding not shadowed at the use site",
                        "module initialization completed",
                        "argument and return type compatibility",
                        "effects and errors preserved",
                    ],
                }
            )
    return {
        "status": "candidates" if candidates else "unknown",
        "context": path,
        "candidates": candidates,
        "issues": sorted(set(issues)),
        "claim": "Explicit access spellings only; absence does not prove unavailability. No replacement or autofix is certified.",
    }
