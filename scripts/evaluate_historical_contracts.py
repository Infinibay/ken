"""Turn three recorded Ken fixes into reproducible, narrowly stated source guards.

Uses git blobs verbatim as data. It never imports or executes historical code,
and all rule/check state belongs to temporary projects.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import time

from ken.checks.rules import manage
from ken.checks.service import check


CASES = [
    {
        "id": "ken.manifest-permissions",
        "commit": "e67c744",
        "path": "src/ken/vectors.py",
        "owner": "_atomic_write",
        "call": "chmod",
        "description": "The manifest writer contains an explicit chmod call; guards the omission fixed in e67c744.",
        "limit": "Does not prove the mode expression, umask behavior, or successful chmod at runtime.",
    },
    {
        "id": "ken.migration-reclaim",
        "commit": "1736a1e",
        "path": "src/ken/cli.py",
        "owner": "_vectors_cli",
        "call": "reclaim_database",
        "description": "The vector CLI invokes reclaim_database; guards the missing reclamation fixed in 1736a1e.",
        "limit": "Does not prove the migrate branch guard, VACUUM execution or physical disk recovery.",
    },
    {
        "id": "ken.nested-gitignore",
        "commit": "7d8a195",
        "path": "src/ken/gitignore_filter.py",
        "owner": "iter_files",
        "call": "is_ignored",
        "description": "File traversal delegates filtering to is_ignored; guards bypass of nested-ignore matching fixed in 7d8a195.",
        "limit": "Does not prove GitignoreMatcher's internal matching algorithm.",
    },
]


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, text=True, capture_output=True
    ).stdout


def evaluate(root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for case in CASES:
        commit = git(root, "rev-parse", case["commit"]).strip()
        before = git(root, "show", f"{commit}^:{case['path']}")
        after = git(root, "show", f"{commit}:{case['path']}")
        query = (
            'language "kql/2"; module ken.history; query guard { '
            "callable $owner { name: " + json.dumps(case["owner"]) + "; "
            "call $site { name: "
            + json.dumps(case["call"])
            + "; } } select $owner,$site; }"
        )
        distractor = "\ndef unrelated_operation():\n    " + case["call"] + "()\n"
        variants = [
            ("historical-before", before, "fail"),
            ("historical-after", after, "pass"),
            ("valid-with-unrelated-operation", after + distractor, "pass"),
            ("unrelated-fix-cannot-mask-bug", before + distractor, "fail"),
        ]
        definition = {
            "id": case["id"],
            "description": case["description"],
            "path": case["path"],
            "query": query,
            "expectation": "some_match",
            "examples": [
                {"name": name, "files": {case["path"]: source}, "expect": expected}
                for name, source, expected in variants
            ],
        }
        folder = output / case["id"]
        folder.mkdir(exist_ok=True)
        (folder / "rule.json").write_text(json.dumps(definition, indent=2) + "\n")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="ken-history-") as temporary:
            project = Path(temporary)
            manage(project, "create", definition=definition)
            validation = manage(
                project, "validate", rule_id=case["id"], timeout_ms=60000
            )
            assert validation["validation"]["passed"], validation
            manage(project, "enable", rule_id=case["id"])
            file = project / case["path"]
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(before)
            failed = check(project, rules=[case["id"]], full=True, timeout_ms=30000)
            file.write_text(after)
            fixed = check(
                project,
                rules=[case["id"]],
                compare=failed["run_id"],
                full=True,
                timeout_ms=30000,
            )
            assert failed["status"] == "fail" and fixed["status"] == "pass", (
                failed,
                fixed,
            )
            assert fixed["comparison"]["changes"][0]["change"] == "resolved"
            (folder / "checks.json").write_text(
                json.dumps([failed, fixed], indent=2) + "\n"
            )
        report = {
            **case,
            "commit": commit,
            "before_sha256": sha256(before.encode()).hexdigest(),
            "after_sha256": sha256(after.encode()).hexdigest(),
            "validation": validation["validation"],
            "before": failed["status"],
            "after": fixed["status"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        reports.append(report)
    result = {
        "cases": reports,
        "claim": "Three real historical regressions discriminated by explicit structural guards; not a general bug detector benchmark.",
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.root.resolve(), args.output.resolve()), indent=2))
