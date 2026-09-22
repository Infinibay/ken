"""Run adopted contracts in CI; uncertainty cannot produce a green build."""

import argparse
import json
from pathlib import Path

from ken.checks.service import check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--rules", nargs="+")
    parser.add_argument("--scope", choices=["project", "changes"], default="project")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()
    result = check(
        args.root.resolve(),
        rules=args.rules,
        scope=args.scope,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "unknown": 2, "not_applicable": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
