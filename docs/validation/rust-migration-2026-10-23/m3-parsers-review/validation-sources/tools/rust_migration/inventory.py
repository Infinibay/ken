"""Capture actual legacy interfaces and assign the complete source inventory."""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .reference import Reference, reference_env

CLI_SCRIPT = '''
import argparse,json
from ken.cli import _build_parser,_build_tool_parser
from ken.mcp.server import list_tools
routes=[]
def walk(parser, command):
    options=[]
    for action in parser._actions:
        if isinstance(action,argparse._SubParsersAction):
            continue
        options.append(dict(dest=action.dest,flags=action.option_strings,required=action.required,
            default=action.default,nargs=action.nargs,choices=action.choices,
            type=getattr(action.type,'__name__',None)))
    routes.append(dict(command=command,options=options,help=parser.format_help()))
    for action in parser._actions:
        if isinstance(action,argparse._SubParsersAction):
            for name,child in action.choices.items():walk(child,command+[name])
walk(_build_parser(),[])
for tool in list_tools():walk(_build_tool_parser(tool),['tools',tool.name])
print(json.dumps(dict(routes=routes),default=str))
'''

MCP_SCRIPT = '''
import asyncio,json,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from ken.mcp.server import list_tools
async def main():
    params=StdioServerParameters(command=sys.executable,args=['-m','ken','mcp',sys.argv[1]])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            response=await session.list_tools()
    print(json.dumps(dict(transport='stdio',tools=[t.model_dump(mode='json',by_alias=True) for t in response.tools],
        local_tools={t.name:t.parameters for t in list_tools()})))
asyncio.run(main())
'''


def _json_process(reference: Reference, code: str, sandbox: Path, *args: str) -> dict:
    result = subprocess.run([str(reference.python), "-c", code, *args], cwd=reference.root,
                            env=reference_env(reference, sandbox), capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"interface capture failed ({result.returncode}): {result.stderr[-4000:]}")
    return json.loads(result.stdout)


def capture_cli(reference: Reference) -> dict:
    with tempfile.TemporaryDirectory(prefix="ken-cli-inventory-") as temp:
        sandbox = Path(temp)
        data = _json_process(reference, CLI_SCRIPT, sandbox)
        env = reference_env(reference, sandbox)
        for route in data["routes"]:
            result = subprocess.run([str(reference.python), "-m", "ken", *route["command"], "--help"],
                                    cwd=sandbox, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError(f"help failed: {route['command']}: {result.stderr[-1000:]}")
            route["help"] = result.stdout
        return data


def capture_mcp(reference: Reference, fixture_root: Path) -> dict:
    marker = fixture_root / ".ken"
    marker.mkdir(parents=True, exist_ok=True)
    (marker / "meta.json").write_text(json.dumps({"project_id": "inventory-fixture", "auth_token": "fixture-token"}))
    result = _json_process(reference, MCP_SCRIPT, fixture_root / "environment", str(fixture_root))
    wire = {t["name"]: t["inputSchema"] for t in result["tools"]}
    if set(wire) != set(result["local_tools"]):
        raise RuntimeError("MCP transport tool names differ from the CLI registry")
    # The SDK adds titles and nullable anyOf/defaults. Keep both contracts;
    # inventory must expose these existing differences, not rewrite either.
    result["schema_differences"] = [name for name in wire if wire[name] != result["local_tools"][name]]
    return result


STAGES = {
    "parsers": ("program_model", "M3"), "common_ast": ("program_model", "M3"),
    "structural": ("structural_analysis", "M5a-M5c"), "structural_store": ("program_store", "M5a"),
    "kql2": ("structural_query", "M5b-M5c"), "retrieval": ("retrieval", "M4"),
    "ranker": ("retrieval", "M4"), "embedder": ("models", "M2"), "bench": ("evaluation", "M4"),
    "code_reasoning": ("code_contract", "M6"), "checks": ("code_contract", "M6"),
    "inspection": ("code_contract", "M6"), "responsibility": ("code_contract", "M6"),
    "reasoning": ("knowledge", "M6"), "knowledge": ("knowledge", "M6"),
    "daemon": ("local_service", "M7"), "mcp": ("public_adapter", "M7"),
    "skills": ("host_integration", "M7"),
}
ROOT_OWNERS = {
    "_paths.py": ("project", "M1"), "tool_paths.py": ("project", "M1"), "status.py": ("status", "M1"),
    "db.py": ("store", "M2"), "schema.sql": ("store", "M2"), "vectors.py": ("store", "M2"),
    "model_assets.py": ("models", "M2"), "reembed.py": ("models", "M2"),
    "indexer.py": ("source_inventory", "M3"), "gitignore_filter.py": ("source_inventory", "M3"),
    "memory.py": ("knowledge", "M6"), "findings_graph.py": ("knowledge", "M6"),
    "search.py": ("retrieval", "M4"), "nametokens.py": ("retrieval", "M4"),
    "cli.py": ("public_adapter", "M7"), "__main__.py": ("public_adapter", "M7"),
    "__init__.py": ("distribution", "M8"), "structure.py": ("program_model", "M3"),
    "jsresolve.py": ("program_model", "M3"), "codeflow.py": ("program_model", "M5a"),
    "graphtools.py": ("program_model", "M5a"), "clones.py": ("retrieval", "M4"),
    "cochange.py": ("retrieval", "M4"), "grep.py": ("retrieval", "M4"),
    "intent.py": ("retrieval", "M4"), "profile.py": ("retrieval", "M4"),
    "presentation.py": ("public_adapter", "M7"), "presentation_views.py": ("public_adapter", "M7"),
}


def source_owners(reference: Reference) -> list[dict]:
    rows = []
    for record in json.loads(reference.manifest_path.read_text())["files"]:
        name = record["path"]
        if not name.startswith("src/ken/"):
            continue
        parts = Path(name).parts[2:]
        concept, stage = STAGES.get(parts[0], ROOT_OWNERS.get(parts[0], ("host_integration", "M7")))
        rows.append({"path": name, "concept": concept, "stage": stage,
                     "evidence": name, "status": "inventariada"})
    return rows


def audit_ownership(reference: Reference, rows: list[dict]) -> list[str]:
    expected = {r["path"] for r in json.loads(reference.manifest_path.read_text())["files"]
                if r["path"].startswith("src/ken/")}
    counts = Counter(row["path"] for row in rows)
    errors = [f"missing:{p}" for p in sorted(expected - counts.keys())]
    errors += [f"duplicate:{p}" for p, n in counts.items() if n > 1]
    errors += [f"unexpected:{p}" for p in sorted(counts.keys() - expected)]
    errors += [f"unassigned:{r['path']}" for r in rows if not all(r.get(k) for k in ["concept", "stage", "evidence"])]
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    reference = Reference.load(args.reference)
    args.out.mkdir(parents=True, exist_ok=True)
    cli = capture_cli(reference)
    with tempfile.TemporaryDirectory(prefix="ken-mcp-inventory-") as temp:
        mcp = capture_mcp(reference, Path(temp))
    owners = source_owners(reference)
    errors = audit_ownership(reference, owners)
    for name, data in [("cli", cli), ("mcp", mcp), ("source-owners", owners)]:
        (args.out / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    (args.out / "capture.json").write_text(json.dumps({"reference": reference.fingerprint, "passed": not errors,
        "routes": len(cli["routes"]), "tools": len(mcp["tools"]), "sources": len(owners), "errors": errors}, indent=2) + "\n")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
