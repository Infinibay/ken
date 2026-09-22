"""Select source dependencies from explicit imports, never from method spelling.

This is an acquisition policy, not a call resolver. KQL independently resolves
symbols in the selected files. Unknown imports cannot establish call edges.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path

from ken.structural.python_imports import targets as python_targets


@dataclass
class Imports:
    root: Path
    paths: set[str]
    edges: dict[str, set[str]] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    names: dict[tuple[str, str], set[str] | None] = field(default_factory=dict)
    spellings: dict[str, set[str]] = field(default_factory=dict)
    deadline: float = field(default_factory=lambda: time.monotonic() + 2.0)

    def read(self, path: str) -> set[str]:
        if time.monotonic() > self.deadline:
            raise ValueError("import discovery time budget exhausted")
        if path in self.edges:
            return self.edges[path]
        targets: set[str] = set()
        self.edges[path] = targets
        try:
            from ken._paths import resolve_project_path

            with resolve_project_path(self.root, path).open("rb") as handle:
                data = handle.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("import discovery file budget exhausted")
            if path.endswith(".py"):
                tree = ast.parse(data)
                self.spellings[path] = set()
                modules: list[tuple[str, int, set[str] | None]] = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        self.spellings[path].add(node.id)
                    elif isinstance(node, ast.Attribute):
                        self.spellings[path].add(node.attr)
                    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                        self.spellings[path].add(node.value)
                    if isinstance(node, ast.Import):
                        modules.extend((a.name, node.lineno, None) for a in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        module = "." * node.level + (node.module or "")
                        names = {a.name for a in node.names}
                        modules.append(
                            (module, node.lineno, None if "*" in names else names)
                        )
                        # `from . import child` can import a submodule.
                        modules.extend(
                            (
                                module + ("." if node.module else "") + a.name,
                                node.lineno,
                                None,
                            )
                            for a in node.names
                            if a.name != "*"
                        )
                for module, line, imported_names in modules:
                    found = python_targets(path, module, self.paths)
                    targets.update(found)
                    for destination in found:
                        key = path, destination
                        previous = self.names.get(key, set())
                        self.names[key] = (
                            None
                            if previous is None or imported_names is None
                            else previous | imported_names
                        )
                    if len(found) > 1:
                        self.issues.append(
                            {
                                "path": path,
                                "line": line,
                                "module": module,
                                "reason": "ambiguous import; include all candidates",
                            }
                        )
            else:
                from ken.parsers import detect_language
                from ken.indexer import _resolve_import_target

                parser = detect_language(Path(path))
                if parser is None:
                    raise ValueError("unsupported import discovery")
                for item in parser[1](data, path).imports:
                    resolved = _resolve_import_target(
                        item.module,
                        sorted(self.paths),
                        files_set=self.paths,
                        source_path=path,
                    )
                    if resolved:
                        targets.add(resolved)
                # Other frontends can have implicit package relationships. Keep
                # the full supplied scope until their import coverage is explicit.
                raise ValueError("implicit/package imports require full-scope analysis")
        except (ValueError, SyntaxError, OSError, RuntimeError) as exc:
            self.issues.append({"path": path, "reason": str(exc)[:180]})
        return targets

    def neighbors(
        self, nodes: list[dict], *, incoming: bool, outgoing: bool
    ) -> set[str]:
        """Acquire one frontier of explicit imports, respecting named bindings."""
        from .graph import qualname

        seeds = {n["path"] for n in nodes}
        selected = set(seeds)
        if outgoing:
            for path in seeds:
                selected.update(self.read(path))
        if incoming:
            for path in sorted(self.paths):
                destinations = self.read(path)
                for node in nodes:
                    if node["path"] not in destinations:
                        continue
                    names = self.names.get((path, node["path"]))
                    # Namespace/star imports can expose any member. An explicit
                    # `from module import Class` can expose its methods, but not
                    # an unrelated top-level helper in that module.
                    name = qualname(node).split(".")[0]
                    if names is None and path in self.spellings:
                        # An explicit namespace/member access must retain the
                        # member spelling. Computed getattr/exec are outside the
                        # modeled static-call coverage, not inferred edges.
                        if name not in self.spellings[path]:
                            continue
                    if names is None or name in names:
                        selected.add(path)
        return set(self.paths) if self.issues else selected

    def closure(
        self, seeds: set[str], *, incoming: bool = False, depth: int = 8
    ) -> set[str]:
        if incoming:
            for path in sorted(self.paths):
                self.read(path)
        seen, frontier = set(seeds), set(seeds)
        for _ in range(depth):
            if incoming:
                added = {p for p, targets in self.edges.items() if targets & frontier}
            else:
                added = set()
                for path in sorted(frontier):
                    added.update(self.read(path))
            frontier = added - seen
            seen.update(added)
            if not frontier:
                break
        if frontier:
            self.issues.append({"reason": "import traversal depth exhausted"})
        if self.issues:
            return set(self.paths)  # conservative acquisition, never invented edges
        return seen


def select(
    root: Path, snapshot: dict, seeds: list[str], *, incoming: bool = False
) -> dict:
    paths = {p for p, _ in snapshot["manifest"]}
    starts = {
        p
        for p in paths
        if any(p == s or p.startswith(s.rstrip("/") + "/") for s in seeds)
    }
    imports = Imports(root, paths)
    selected = imports.closure(starts)
    if incoming:
        # Follow each direction from the requested files independently. A
        # shared helper does not connect all of its importers to the target.
        selected |= imports.closure(starts, incoming=True)
    return {
        "paths": sorted(selected),
        "issues": imports.issues,
        "basis": "explicit imports; unresolved acquisition falls back to supplied scope",
    }


def dependencies(root: Path, snapshot: dict, *, seconds: float = 2.0) -> dict:
    """Fingerprint imports outside a rule's declared evaluation domain.

    Imported files are dependencies, not extra places allowed to satisfy the
    rule. Re-discovery notices newly resolvable imports as well as deletions.
    """
    from ken.gitignore_filter import iter_files
    from ken.knowledge.dependencies import Fingerprints
    from ken.structural.frontend import LANGUAGES

    started = time.monotonic()
    if snapshot["scope"] == ".":
        return {"manifest": [], "imports": []}
    paths: set[str] = set()
    for p in iter_files(root):
        if time.monotonic() - started > seconds or len(paths) > 4000:
            raise ValueError("import dependency inventory budget exhausted")
        if p.suffix in LANGUAGES:
            paths.add(p.as_posix())
    seeds = {p for p, _ in snapshot["manifest"]}
    imports = Imports(root, paths, deadline=started + seconds)
    closure = imports.closure(seeds)
    fingerprints = Fingerprints(
        root, seconds=max(0.001, seconds - (time.monotonic() - started))
    )
    manifest = []
    for path in sorted(closure - seeds):
        entry = fingerprints.snapshot({"path": path})
        manifest.append([path, entry["sha256"]])
    return {
        "manifest": manifest,
        "imports": [
            [p, sorted(targets)] for p, targets in sorted(imports.edges.items())
        ],
        "issues": imports.issues,
    }
