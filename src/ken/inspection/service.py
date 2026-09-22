"""Public inspection use cases share program acquisition and bounded evidence."""

from pathlib import Path

from ken._paths import resolve_project_path

from .graph import Program, acquisition_view
from .impact import analyze
from .roles import describe


def inspect(
    root: Path,
    target: str,
    *,
    relation: str = "impact",
    path: str = ".",
    depth: int = 2,
    limit: int = 10,
    timeout_ms: int = 10000,
    full: bool = False,
    from_path: str = "",
) -> dict:
    if not 1 <= depth <= 8 or not 1 <= limit <= 100:
        raise ValueError("depth must be 1..8 and limit 1..100")
    if relation not in {"impact", "roles", "available"}:
        raise ValueError("relation must be impact, roles or available")
    if not isinstance(target, str) or not target.strip() or len(target) > 2000:
        raise ValueError("target must be a nonempty path or symbol")
    root = root.resolve()
    path = resolve_project_path(root, path).relative_to(root).as_posix()
    file, separator, symbol = target.partition("::")
    is_path = bool(separator or "/" in file or (root / file).exists())
    if is_path:
        file = resolve_project_path(root, file).relative_to(root).as_posix()
        target = file + (separator + symbol if separator else "")
    seeds = [file] if is_path else None
    if relation == "available":
        if not from_path:
            raise ValueError("available requires from_path")
        from_path = (
            resolve_project_path(root, from_path).relative_to(root.resolve()).as_posix()
        )
        seeds = [*(seeds or []), from_path]
    program = Program.inspect(
        root,
        path=path,
        timeout_ms=timeout_ms,
        seeds=seeds,
        incoming=relation != "available",
        focus={"targets": [target], "relation": relation, "depth": depth},
    )
    seeds = program.select(target)
    if relation == "available":
        from .availability import describe as available

        result = available(root, program, seeds, from_path)
    elif relation == "roles":
        result = describe(program, seeds, depth=depth, limit=limit)
    else:
        result = analyze(program, seeds, depth=depth, limit=limit)
    result.setdefault("status", "observed" if seeds else "unknown")
    result["acquisition"] = acquisition_view(program.selection, full=full)
    if not seeds:
        result["reason"] = (
            "Analysis incomplete; inspect coverage for budgets or unsupported code."
            if any(not item.get("complete") for item in program.coverage().values())
            else "Target not resolved in the inspected scope; qualify with file::symbol."
        )
    if full:
        result["observations"] = program.observations
        result["snapshot"] = program.snapshot
    return result
