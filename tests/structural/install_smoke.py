"""Install the built wheel with uv in isolation and exercise its installed CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="ken-wheel-smoke-") as temporary:
        root = Path(temporary)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["UV_TOOL_DIR"] = str(root / "tools")
        env["UV_TOOL_BIN_DIR"] = str(root / "bin")
        subprocess.run(["uv", "tool", "install", "--python", sys.executable, str(wheel)], env=env, check=True)
        executable = root / "bin/ken"
        result = subprocess.run([str(executable), "structural", "catalog"], cwd=root, env=env, capture_output=True, text=True, check=True)
        assert len(json.loads(result.stdout)["patterns"]) == 23
        (root / "sample.py").write_text("def search(user: str) -> str:\n return user\n")
        result = subprocess.run([str(executable), "structural", "search", "--path", str(root), "--scope", "sample.py",
                                 "--cache-mb", "0", "--query", 'method(name: /^search$/i) as $m { has_parameter(type: str) as $p; }'],
                                cwd=root, env=env, capture_output=True, text=True, check=True)
        assert len(json.loads(result.stdout)["matches"]) == 1
        (root / "generator.py").write_text("def items():\n yield 1\n")
        result = subprocess.run([str(executable), "structural", "search", "--path", str(root), "--scope", "generator.py",
                                 "--cache-mb", "0", "--query", 'query q { match "gof.iterator#generator"(iterator:$i); emit $i; }'],
                                cwd=root, env=env, capture_output=True, text=True, check=True)
        assert len(json.loads(result.stdout)["matches"]) == 1
        print("Wheel installed with uv tool install; catalogue and regex/IR query passed.")


if __name__ == "__main__":
    main()
