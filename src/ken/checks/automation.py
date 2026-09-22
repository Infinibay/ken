"""Coalesce edit events and deliver bounded check updates at the next prompt."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Callable

from .model import digest
from .service import check, latest
from .integration import freshness
from .store import Store

logger = logging.getLogger(__name__)


def message(receipt: dict) -> str:
    lines = [f"{c['rule']}: {c['status']}" for c in receipt["checks"]]
    lines.extend(
        f"{r['rule']}: {r['reason']}" for r in receipt.get("skipped_rules", [])
    )
    for change in receipt.get("comparison", {}).get("changes", []):
        if change["change"] in {"regression", "resolved", "inconclusive"}:
            lines.append(f"{change['rule']}: {change['change']}")
    if not lines:
        return ""
    return (
        "<ken-checks>\n"
        + "; ".join(lines)[:900]
        + f'\nScope: selected source contracts. Inspect: ken_check(run_id="{receipt["run_id"]}", full=true).\n</ken-checks>'
    )


def resume(root: Path) -> str:
    receipt = latest(Store(root))
    if receipt is None:
        return ""
    live = freshness(root, receipt)
    return (
        f"<ken-checks>\nLast source-contract check: {receipt['status']}; input validity: {live['state']}. "
        f'Inspect: ken_check(run_id="{receipt["run_id"]}"). Recheck if inputs changed.\n</ken-checks>'
    )


class Scheduler:
    """One background worker per daemon; no source analysis inside its DB lock."""

    def __init__(
        self,
        root: Path,
        *,
        delay: float = 0.5,
        timeout_ms: int = 3000,
        runner: Callable = check,
    ):
        self.root, self.delay, self.timeout_ms, self.runner = (
            root,
            delay,
            timeout_ms,
            runner,
        )
        self.lock = threading.Lock()
        self.pending: dict[str, set[str]] = {}
        self.notices: dict[str, str] = {}
        self.signatures: dict[str, str] = {}
        self.baselines: dict[str, str] = {}
        self.timer: threading.Timer | None = None
        self.running = False
        self.closed = False

    def enqueue(self, session: str, paths: list[str]) -> None:
        if not any(r["enabled"] and r["automatic"] for r in Store(self.root).rules()):
            return
        with self.lock:
            if self.closed:
                return
            self.pending.setdefault(session, set()).update(paths)
            if self.timer is not None:
                self.timer.cancel()
            if not self.running:
                self._schedule()

    def _schedule(self) -> None:
        self.timer = threading.Timer(self.delay, self._work)
        self.timer.daemon = True
        self.timer.start()

    def _work(self) -> None:
        with self.lock:
            if self.closed or self.running:
                return
            pending, self.pending = self.pending, {}
            self.running = True
            self.timer = None
        try:
            for session, paths in pending.items():
                try:
                    result = self.runner(
                        self.root,
                        scope="changes",
                        automatic=True,
                        touched=sorted(paths) or None,
                        compare=self.baselines.get(session, ""),
                        timeout_ms=self.timeout_ms,
                    )
                    if not result["checks"] and not result.get("skipped_rules"):
                        continue
                    signature = digest([result["checks"], result.get("skipped_rules")])
                    with self.lock:
                        if self.closed:
                            return
                        if self.signatures.get(session) != signature:
                            self.notices[session] = message(result)
                            self.signatures[session] = signature
                        self.baselines[session] = result["run_id"]
                except Exception:
                    logger.exception("automatic contract check failed")
        finally:
            with self.lock:
                self.running = False
                if self.pending and not self.closed:
                    self._schedule()

    def drain(self, session: str) -> str:
        with self.lock:
            return self.notices.pop(session, "")

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.timer is not None:
                self.timer.cancel()
            self.pending.clear()


def scheduler(state) -> Scheduler:
    with state.lock:
        if not hasattr(state, "contract_checks"):
            state.contract_checks = Scheduler(state.project_root)
        return state.contract_checks


def edited_paths(root: Path, tool_input, target: str | None) -> list[str]:
    """Capture all patch paths; fallback to Git changes when paths are unavailable."""
    import re

    values = [target] if target else []
    text = (
        tool_input
        if isinstance(tool_input, str)
        else str(tool_input.get("patch", ""))
        if isinstance(tool_input, dict)
        else ""
    )
    values.extend(
        re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", text, re.MULTILINE)
    )
    paths = []
    for value in values:
        if value is None:
            continue
        try:
            path = (root / value).resolve().relative_to(root.resolve()).as_posix()
            if ".ken" not in Path(path).parts and ".git" not in Path(path).parts:
                paths.append(path)
        except ValueError:
            continue
    return list(dict.fromkeys(paths))
