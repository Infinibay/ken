"""Rule lifecycle: authored definition, tested examples, explicit enablement."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
import time
from typing import Any

from . import execution
from .model import Rule, judgment
from .snapshot import engine_version
from .store import Store


def validated(record: dict, version: str) -> bool:
    validation = record.get("validation") or {}
    return (
        validation.get("passed") is True
        and validation.get("revision") == Rule.read(record["definition"]).revision
        and validation.get("engine") == version
    )


def view(record: dict, *, full: bool = False, version: str | None = None) -> dict:
    rule = Rule.read(record["definition"])
    ready = validated(record, version or engine_version())
    state = (
        "enabled" if ready and record["enabled"] else "validated" if ready else "draft"
    )
    out = {
        "id": rule.id,
        "description": rule.description,
        "path": rule.path,
        "expectation": rule.expectation,
        "state": state,
        "automatic": bool(ready and record["enabled"] and record["automatic"]),
        "revision": rule.revision,
    }
    if full:
        out.update(definition=asdict(rule), validation=record.get("validation"))
    return out


def manage(
    root: Path,
    action: str = "list",
    *,
    rule_id: str = "",
    definition: dict | None = None,
    automatic: bool | None = None,
    timeout_ms: int = 30000,
    full: bool = False,
) -> dict:
    if not 1 <= timeout_ms <= 120000:
        raise ValueError("timeout_ms must be 1..120000")
    store = Store(root)
    version = engine_version()
    if action == "list":
        return {"rules": [view(r, full=full, version=version) for r in store.rules()]}
    if action == "create":
        if definition is None:
            raise ValueError("create requires definition")
        rule = Rule.read(definition)
        if rule_id and rule_id != rule.id:
            raise ValueError("rule_id conflicts with definition id")
        # Compile through the same public compiler before recording a definition.
        from ken.kql2.compilation import compile_query
        from ken.kql2.catalog import with_packaged_libraries

        compile_query(
            root,
            rule.query,
            None,
            budget_bytes=0,
            libraries=with_packaged_libraries(rule.query, rule.libraries),
        )
        record: dict[str, Any] = {
            "version": 1,
            "definition": asdict(rule),
            "enabled": False,
            "automatic": False,
            "validation": None,
        }
        store.save_rule(record, None)
        return view(record, full=full, version=version)
    previous = store.read("rules", rule_id)
    record = dict(previous)
    rule = Rule.read(record["definition"])
    if action == "show":
        return view(record, full=full, version=version)
    if action == "update":
        if definition is None:
            raise ValueError("update requires a complete definition")
        replacement = Rule.read(definition)
        if replacement.id != rule.id:
            raise ValueError("update cannot rename a rule")
        from ken.kql2.compilation import compile_query
        from ken.kql2.catalog import with_packaged_libraries

        compile_query(
            root,
            replacement.query,
            None,
            budget_bytes=0,
            libraries=with_packaged_libraries(replacement.query, replacement.libraries),
        )
        record.update(
            definition=asdict(replacement),
            enabled=False,
            automatic=False,
            validation=None,
        )
    elif action == "validate":
        expected = {case["expect"] for case in rule.examples}
        if not {"pass", "fail"} <= expected:
            raise ValueError("validation requires both passing and failing examples")
        deadline = time.monotonic() + timeout_ms / 1000
        cases = []
        for example in rule.examples:
            with tempfile.TemporaryDirectory(prefix="ken-rule-") as folder:
                project = Path(folder)
                for path, source in example["files"].items():
                    file = project / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(source)
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                result = execution.run(
                    project,
                    rule.query,
                    path=rule.path,
                    libraries=rule.libraries,
                    timeout_ms=remaining,
                    max_rows=100,
                    cache_mb=0,
                )
                actual = judgment(result, rule.expectation)
                cases.append(
                    {
                        "name": example["name"],
                        "expected": example["expect"],
                        "actual": actual,
                        "passed": actual == example["expect"],
                        "reason": result.get("reason"),
                    }
                )
        record.update(
            enabled=False,
            automatic=False,
            validation={
                "revision": rule.revision,
                "engine": version,
                "passed": all(c["passed"] for c in cases),
                "cases": cases,
            },
        )
    elif action == "enable":
        if not validated(record, version):
            raise ValueError(
                "validate passing and failing examples against this rule and engine before enabling"
            )
        record["enabled"] = True
        if automatic is not None:
            record["automatic"] = automatic
    elif action == "disable":
        record.update(enabled=False, automatic=False)
    else:
        raise ValueError(
            "action must be list/create/show/update/validate/enable/disable"
        )
    store.save_rule(record, previous)
    return view(record, full=full or action == "validate", version=version)
