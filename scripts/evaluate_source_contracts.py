"""Exercise source-contract tools on an isolated copy of Ken's actual report code."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from ken.checks.automation import Scheduler
from ken.checks.service import check
from ken.db import connect, init_schema
from ken.mcp import server


QUERY = """language "kql/2"; module ken.validation;
query full_response {
  callable $f { name: "query_view";
    param $input { name: "result"; }
    body { return read($input); }
  }
  select $f;
}"""


def evaluate(repository: Path, output: Path) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    relative = "src/ken/checks/report.py"
    original = (repository / relative).read_text()
    output.mkdir(parents=True, exist_ok=True)
    events = []
    with tempfile.TemporaryDirectory(prefix="ken-contract-evaluation-") as directory:
        root = Path(directory)
        file = root / relative
        file.parent.mkdir(parents=True)
        file.write_text(original)
        (root / ".ken").mkdir()
        (root / ".ken/meta.json").write_text("{}")
        with connect(root / ".ken/ken.db") as conn:
            init_schema(conn)
        server._PROJECT_ROOT = root

        def call(name, **arguments):
            value = getattr(server, name)(**arguments)
            events.append({"tool": name, "arguments": arguments, "result": value})
            return value

        definition = {
            "id": "report.full-response",
            "description": "query_view has a source path that returns its original result parameter",
            "path": relative,
            "query": QUERY,
            "expectation": "some_match",
            "examples": [
                {
                    "name": "passthrough",
                    "files": {
                        relative: "def query_view(result, full=False):\n if full: return result\n return {}\n"
                    },
                    "expect": "pass",
                },
                {
                    "name": "discarded",
                    "files": {
                        relative: "def query_view(result, full=False):\n if full: return {}\n return {}\n"
                    },
                    "expect": "fail",
                },
            ],
        }
        call("ken_rule", action="create", definition=definition)
        validation = call("ken_rule", action="validate", rule_id=definition["id"])
        assert validation["state"] == "validated", validation
        call("ken_rule", action="enable", rule_id=definition["id"], automatic=True)
        before = call("ken_check", full=True)
        assert before["status"] == "pass", before
        memory = call(
            "ken_remember",
            topic="report-original-response",
            content="The observed query_view implementation can return its original result parameter.",
            check_run=before["run_id"],
            anchor_file=relative,
        )
        assert memory["ok"], memory
        found = call("ken_find", scope="structure", rules=[definition["id"]])
        assert found["results"][0]["result"]["rows"]
        call("ken_related", target=relative, relation="checks")

        modified = original.replace(
            "if full:\n        return result", "if full:\n        return {}", 1
        )
        assert modified != original
        file.write_text(modified)
        after = call("ken_check", compare=before["run_id"], full=True)
        assert after["status"] == "fail", after
        assert after["comparison"]["changes"][0]["change"] == "regression"
        recall = call("ken_recall", topic="report-original-response", detail="summary")
        assert recall["memories"][0]["validity"]["state"] == "stale"
        file.write_text(original)
        fixed = call("ken_check", compare=after["run_id"], full=True)
        assert fixed["comparison"]["changes"][0]["change"] == "resolved"

        ready = threading.Event()

        def automatic(*args, **kwargs):
            result = check(*args, **kwargs)
            ready.set()
            return result

        scheduler = Scheduler(root, delay=0.05, runner=automatic)
        try:
            file.write_text(modified)
            scheduler.enqueue("evaluation", [relative])
            assert ready.wait(5)
            deadline = time.monotonic() + 5
            notice = ""
            while not notice and time.monotonic() < deadline:
                notice = scheduler.drain("evaluation")
                if not notice:
                    time.sleep(0.01)
            assert "fail" in notice
        finally:
            scheduler.close()
        report = {
            "source": relative,
            "source_sha256": sha256(original.encode()).hexdigest(),
            "scope": "Isolated exact copy of Ken source, then one deliberate mutation; no edits to the working source",
            "before": before["status"],
            "mutated": after["status"],
            "restored": fixed["status"],
            "comparison": after["comparison"]["changes"],
            "memory_after_mutation": "stale",
            "automatic_notice": notice,
            "claim": "Existence of a source return of the selected parameter; not a universal branch or runtime guarantee.",
        }
        (output / "events.json").write_text(
            json.dumps(events, indent=2, ensure_ascii=False) + "\n"
        )
        (output / "result.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(args.root.resolve(), args.output), indent=2, ensure_ascii=False
        )
    )
