"""Capture actual CLI and persistent MCP output on a small disposable project."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile

from ken.cli import main
from ken.db import connect, init_schema
from ken.embedder import get_embedder, record_model, recommended_model
from ken.indexer import index_files
from ken.mcp import server
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def run(output):
    root = Path(tempfile.mkdtemp(prefix="ken-output-demo-", dir="/private/tmp"))
    sources = {
        "settings.py": '"""Store and retrieve application settings."""\nVALUES = {"color": "blue"}\n\ndef get_value(key):\n    """Read a stored setting."""\n    return VALUES[key]\n',
        "reader.py": 'from settings import get_value\n\nclass Reader:\n    """Read stored application settings."""\n\n    def read_value(self, key):\n        """Return the stored value for a setting key."""\n        return get_value(key)\n',
        "tests/test_reader.py": 'from reader import Reader\n\ndef test_read_value():\n    assert Reader().read_value("color") == "blue"\n',
    }
    (root / ".ken").mkdir()
    (root / ".ken/meta.json").write_text(json.dumps({"project_id": "compact-output-demo", "created_at": "2026-10-16T00:00:00Z"}))
    for name, content in sources.items():
        p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
    with connect(root / ".ken/ken.db") as conn:
        init_schema(conn)
        record_model(conn, recommended_model())
        index_files(conn, root, list(map(Path, sources)), embedder=get_embedder())
    calls = [
        ("ken_find", {"query": "Reader.read_value", "scope": "symbols"}),
        ("ken_read", {"path": "reader.py", "include": ["source"], "qualname": "Reader.read_value"}),
        ("ken_related", {"target": "reader.py", "relation": "neighbors"}),
        ("ken_rank", {"scope": "project"}),
        ("ken_rule", {"action": "list"}),
        ("ken_check", {}),
        ("ken_who", {"question": "Who reads stored application settings?"}),
        ("ken_remember", {"topic": "settings-reader", "content": "Reader.read_value delegates lookup to settings.get_value.", "anchor_file": "reader.py"}),
        ("ken_recall", {"topic": "settings-reader", "detail": "answer"}),
        ("ken_reason_record", {"source": "demo-doc", "facts": [{"predicate": "reads", "subject": "Reader", "object": "settings"}], "evidence": "reader.py class docstring"}),
        ("ken_reason", {"question": "Who reads settings?", "goal": {"predicate": "reads", "subject": "?answer", "object": "settings"}}),
        ("ken_calculate", {"expression": "(1/3 + 1/6) * 6"}),
    ]
    captured = []
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ken", "mcp", str(root)],
            env={"PYTHONPATH": str(Path(server.__file__).resolve().parents[2]), "PYTHONDONTWRITEBYTECODE": "1"})
        with (root / "mcp.log").open("w") as log:
            async with stdio_client(params, errlog=log) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for name, args in calls:
                        result = await session.call_tool(name, args)
                        if result.is_error:
                            raise RuntimeError((name, result))
                        text = "\n".join(c.text for c in result.content if c.type == "text")
                        captured.append({"transport": "MCP", "tool": name, "arguments": args, "output": text})
    asyncio.run(exercise())
    q = root / "readers.kql"
    q.write_text('language "kql/2"; module demo; query readers { class $c {} select $c.name; }')
    cli = [
        ["search-symbols", "Reader.read_value"],
        ["search-files", "reader"],
        ["status", str(root)],
        ["kql2", str(q), "--root", str(root), "--cache-mb", "0"],
        ["structural", "search", "--path", str(root), "--query", 'method(name: /^read_value$/) as $m;', "--cache-mb", "0"],
        ["tools", "--path", str(root), "read", "reader.py", "--include", "source", "--qualname", "Reader.read_value"],
        ["tools", "--path", str(root), "--json", "read", "reader.py", "--include", "source", "--qualname", "Reader.read_value"],
    ]
    for args in cli:
        if args[0].startswith("search-"):
            args += ["--path", str(root)]
        stdout = io.StringIO(); stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(args)
        captured.append({"transport": "CLI", "argv": args, "exit_code": status, "output": stdout.getvalue(), "stderr": stderr.getvalue()})
    output.mkdir(parents=True, exist_ok=False)
    (output / "captures.json").write_text(json.dumps(captured, ensure_ascii=False, indent=2))
    markdown = ["# Actual compact output examples", "", "Captured from a disposable three-file project through CLI and one persistent MCP session. These demonstrate presentation, not a retrieval-quality benchmark. All output is captured verbatim. Path of the temporary fixture: " + str(root), ""]
    for row in captured:
        label = row.get("tool") or "ken " + " ".join(row["argv"])
        markdown += ["## " + label, ""]
        if row["transport"] == "MCP":
            markdown += ["Arguments: `" + json.dumps(row["arguments"], ensure_ascii=False) + "`", ""]
        markdown += ["```text", row["output"].rstrip("\n"), "```", ""]
        if row.get("stderr"):
            markdown += ["stderr:", "```text", row["stderr"].rstrip("\n"), "```", ""]
    (output / "EXAMPLES.md").write_text("\n".join(markdown))
    print(json.dumps({"tools": len(calls), "CLI_examples": len(cli), "captures_sha256": hashlib.sha256((output / "captures.json").read_bytes()).hexdigest(), "output": str(output)}))


if __name__ == "__main__":
    run(Path(sys.argv[1]))
