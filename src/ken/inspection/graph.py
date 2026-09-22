"""Normalize KQL witnesses into a navigable, explicitly partial program view."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ken.checks.execution import run_batch
from ken.checks.model import relative
from .queries import QUERIES


def identity(value) -> str:
    return value.get("local_id", "") if isinstance(value, dict) else str(value)


def location(node: dict) -> dict:
    return {k: node[k] for k in ("path", "line", "name", "kind") if k in node}


def qualname(node: dict) -> str:
    import re

    return ".".join(
        re.findall(r"/(?:CALLABLE|CLASS|INTERFACE):([^/@]+)", node["local_id"])
    )


@dataclass
class Program:
    scope: str
    observations: dict
    nodes: dict[str, dict]
    calls: list[dict]
    uses: list[dict]
    snapshot: dict | None
    selection: dict | None = None

    @classmethod
    def inspect(
        cls,
        root: Path,
        *,
        path: str = ".",
        timeout_ms: int = 10000,
        seeds: list[str] | None = None,
        incoming: bool = False,
        focus: dict | None = None,
    ) -> Program:
        path = relative(path)
        batch = run_batch(
            root,
            QUERIES,
            path=path,
            timeout_ms=timeout_ms,
            seeds=seeds,
            incoming=incoming,
            focus=focus,
        )
        return cls.from_batch(path, batch)

    @classmethod
    def from_batch(cls, path: str, batch: dict) -> Program:
        observations = batch["results"]
        nodes = {
            identity(row[0]): row[0]
            for row in observations["definitions"].get("rows", [])
            if isinstance(row[0], dict)
        }
        entities = {}
        for result in observations.values():
            entities.update(result.get("entities", {}))
        nodes.update(
            (key, node) for key, node in entities.items() if node["kind"] == "CALLABLE"
        )
        targets: dict[str, list[str]] = {}
        possible: dict[str, list[str]] = {}
        for key, destination in (("targets", targets), ("possible_targets", possible)):
            for site, target in observations[key].get("rows", []):
                destination.setdefault(identity(site), []).append(identity(target))
        calls = []
        for owner, site in observations["calls"].get("rows", []):
            owner = nodes.get(identity(owner), owner)
            site = entities.get(identity(site), site)
            if not isinstance(owner, dict) or not isinstance(site, dict):
                continue
            nodes.setdefault(identity(owner), owner)
            linked = targets.get(identity(site), [])
            alternatives = possible.get(identity(site), [])
            calls.append(
                {
                    "owner": identity(owner),
                    "site": site,
                    "targets": linked or alternatives,
                    "resolution": "resolved"
                    if linked
                    else "ambiguous"
                    if alternatives
                    else "unresolved",
                }
            )
        uses = []
        for owner, target, site, use in observations["usages"].get("rows", []):
            if isinstance(use, dict):
                uses.append(
                    {
                        "owner": identity(owner),
                        "target": identity(target),
                        "site": identity(site),
                        "usage": use,
                    }
                )
        return cls(
            path,
            observations,
            nodes,
            calls,
            uses,
            batch.get("snapshot"),
            batch.get("selection"),
        )

    def select(self, target: str) -> list[str]:
        """Accept file, qualname, or file::qualname; never conflate homonyms."""
        path, separator, symbol = target.partition("::")
        selected = []
        for key, node in self.nodes.items():
            matches_path = node["path"] == path or node["path"].startswith(
                path.rstrip("/") + "/"
            )
            if separator:
                matches = matches_path and qualname(node) == symbol
            else:
                matches = matches_path or qualname(node) == target
            if matches:
                selected.append(key)
        return selected

    def coverage(self) -> dict:
        out = {}
        for name, result in self.observations.items():
            out[name] = {
                k: result[k]
                for k in (
                    "complete",
                    "coverage_complete",
                    "unknown_candidates",
                    "results_truncated",
                    "reason",
                )
                if k in result
            }
            if "queries" in result:
                out[name]["evaluations"] = len(result["queries"])
        return out

    def inventory_complete(self) -> bool:
        return all(
            r.get("complete")
            and r.get("coverage_complete")
            and not r.get("results_truncated")
            and not r.get("reason")
            for k, r in self.observations.items()
            if k != "usages"
        )

    def connected(self, seeds: list[str], *, depth: int = 2) -> set[str]:
        seen, frontier = set(seeds), set(seeds)
        for _ in range(depth):
            added = set()
            for call in self.calls:
                if call["owner"] in frontier or set(call["targets"]) & frontier:
                    added.add(call["owner"])
                    added.update(call["targets"])
            frontier = added - seen
            seen.update(added)
        return seen


def acquisition_view(selection: dict | None, *, full: bool = False) -> dict | None:
    if selection is None or full:
        return selection
    return {k: value for k, value in selection.items() if k != "steps"}
