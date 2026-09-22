"""Explore requested identities one import frontier at a time, inside a worker."""

from __future__ import annotations

import json
from pathlib import Path
import time

from ken.checks.snapshot import capture, engine_version
from ken.kql2.service import search

from .graph import Program, identity
from .impact import result_uses
from .imports import Imports
from .observations import Observations
from . import queries


class Explorer:
    """Coordinate acquisition and KQL observations; the engine owns semantics."""

    def __init__(self, request: dict):
        self.root = Path(request["root"])
        self.scope = request["path"]
        self.focus = request["focus"]
        seconds = request["timeout_ms"] / 1000
        self.deadline = time.monotonic() + max(0, seconds - min(0.5, seconds / 10))
        self.log = Observations()
        self.before = capture(self.root, self.scope, seconds=self.remaining() / 1000)
        self.version = engine_version()
        self.paths = {p for p, _ in self.before["manifest"]}
        self.imports = Imports(self.root, self.paths, deadline=self.deadline)
        self.steps: list[dict] = []
        self.max_rows = request["max_rows"]

    def remaining(self) -> int:
        milliseconds = int((self.deadline - time.monotonic()) * 1000)
        if milliseconds <= 0:
            raise TimeoutError("inspection time budget exhausted")
        return milliseconds

    def observe(self, name: str, query: str, paths: set[str]) -> dict:
        result = search(
            self.root,
            query,
            path=self.scope,
            source_paths=sorted(paths),
            include_entities=True,
            timeout_ms=self.remaining(),
            max_rows=self.max_rows,
            max_states=200000,
            cache_mb=100,
        )
        self.log.add(name, query, result)
        return result

    def program(self) -> Program:
        return Program.from_batch(
            self.scope, {"results": self.log.results, "snapshot": self.before}
        )

    def locate(self) -> list[str]:
        targets = self.focus["targets"]
        files = {target.partition("::")[0] for target in targets}
        selected = {
            p
            for p in self.paths
            if any(p == f or p.startswith(f.rstrip("/") + "/") for f in files)
        }
        selector = ""
        if len(targets) == 1:
            file, separator, symbol = targets[0].partition("::")
            if separator or not selected:
                name = (symbol if separator else file).rsplit(".", 1)[-1]
                selector = f"name:{json.dumps(name)};"
        # A missing qualified path must not turn into an unrelated global scan.
        if not selected and not any("::" in t or "/" in t for t in targets):
            selected = self.paths
        self.observe(
            "definitions",
            queries.query(f"callable $f {{{selector}}} select $f;"),
            selected,
        )
        program = self.program()
        return list(
            dict.fromkeys(key for target in targets for key in program.select(target))
        )

    def step(
        self, frontier: list[str], *, incoming: bool, outgoing: bool, uses: bool
    ) -> None:
        program = self.program()
        nodes = [program.nodes[key] for key in frontier]
        paths = self.imports.neighbors(nodes, incoming=incoming, outgoing=outgoing)
        self.steps.append({"symbols": frontier, "paths": sorted(paths)})
        calls = self.observe(
            "calls",
            queries.neighbors(frontier, incoming=incoming, outgoing=outgoing),
            paths,
        )
        sites = sorted({identity(row[1]) for row in calls.get("rows", [])})
        if sites:
            self.observe("targets", queries.targets(sites), paths)
            self.observe(
                "possible_targets", queries.targets(sites, possible=True), paths
            )
            if uses:
                self.observe("usages", queries.usages(sites), paths)

    def run(self) -> dict:
        frontier: list[str] = []
        visited: set[str] = set()
        relation = self.focus["relation"]
        try:
            frontier = self.locate()
            if relation == "available":
                frontier = []  # Explicit access spellings need declarations, not BODY.
            for _ in range(self.focus["depth"]):
                if not frontier:
                    break
                if len(frontier) > 100:
                    self.log.fail("inspection frontier exceeds 100 symbols")
                    break
                self.remaining()
                self.step(
                    frontier,
                    incoming=relation != "outgoing",
                    outgoing=relation in {"roles", "outgoing"},
                    uses=relation in {"impact", "outgoing"},
                )
                if self.log.invalidated:
                    break
                visited.update(frontier)
                program = self.program()
                if relation == "impact":
                    following = {
                        call["owner"]
                        for call in program.calls
                        if call["resolution"] == "resolved"
                        and any(
                            u["kind"] == "return"
                            for target in set(call["targets"]) & set(frontier)
                            for u in result_uses(program, call, target)
                        )
                    }
                elif relation == "outgoing":
                    following = {
                        target
                        for call in program.calls
                        if call["owner"] in frontier
                        for target in call["targets"]
                    }
                else:
                    following = program.connected(frontier, depth=1)
                frontier = sorted((following - visited) & program.nodes.keys())
        except (TimeoutError, ValueError, OSError, RuntimeError) as exc:
            self.log.fail(str(exc))
        try:
            after = capture(self.root, self.scope)
            expected = dict(self.before["manifest"])
            if (
                after != self.before
                or self.version != engine_version()
                or any(expected.get(p) != h for p, h in self.log.manifest.items())
            ):
                self.log.fail("source_changed_during_inspection", discard=True)
        except (ValueError, OSError) as exc:
            self.log.fail(str(exc))
        if self.imports.issues:
            self.log.fail("import discovery incomplete; supplied scope retained")
        selection = {
            "basis": "requested identities and explicit imports, one frontier at a time",
            "claim": "Statically modeled calls; computed imports/member names and runtime dispatch are not traced.",
            "paths": sorted(self.log.paths),
            "issues": self.imports.issues,
            "steps": self.steps,
            "import_files_read": len(self.imports.edges),
            "expanded_symbols": len(visited),
            "depth_limited": bool(frontier),
        }
        return self.log.batch(self.before, self.version, selection)


def evaluate(request: dict) -> dict:
    return Explorer(request).run()
