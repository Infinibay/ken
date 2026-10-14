import json
from pathlib import Path

import numpy as np

from ken import _paths
from ken.db import connect, init_schema
from ken.retrieval.indexing import index_project
from ken.retrieval.profile import EncoderSpec, RetrievalProfile


class Encoder:
    def embed_passages(self, texts):
        return [np.array([1., 0.], dtype=np.float32) for _ in texts]
    def embed_query(self, query):
        return np.array([1., 0.], dtype=np.float32)


def project(tmp_path, monkeypatch):
    _paths.ken_dir(tmp_path).mkdir()
    _paths.meta_path(tmp_path).write_text("{}")
    (tmp_path / "client.py").write_text("def redirect(headers):\n    headers.pop('Authorization', None)\n")
    spec = EncoderSpec("test/provided", "d" * 40, "provided")
    profile = RetrievalProfile(spec, spec)
    encoder = Encoder()
    monkeypatch.setattr("ken.retrieval.candidates.load_encoder", lambda spec: encoder)
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
        index_project(conn, tmp_path, [Path("client.py")], profile=profile,
                      encoders={"identity": encoder, "behavior": encoder})


def test_mcp_and_cli_return_same_order_and_evidence(tmp_path, monkeypatch, capsys):
    from ken.cli import main
    from ken.mcp import server
    project(tmp_path, monkeypatch)
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    response = server.ken_find("remove credentials", scope="symbols", response_format="evidence")
    assert main(["search-symbols", "remove credentials", "--path", str(tmp_path),
                 "--response-format", "evidence", "--json"]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == response
    assert cli["results"][0]["entity"]["qualname"] == "redirect"
    assert "headers.pop" in cli["results"][0]["evidence"][0]["content"]


def test_unmigrated_project_returns_actionable_state(tmp_path, monkeypatch):
    from ken.mcp import server
    _paths.ken_dir(tmp_path).mkdir()
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    response = server.ken_find("remove credentials", scope="symbols", response_format="evidence")
    assert response["ok"] is False
    assert response["code"] == "retrieval_index_required"
    assert "ken retrieval index" in response["next_action"]


def test_evidence_schema_is_explicit_and_legacy_is_default():
    from ken.mcp.server import list_tools
    schema = next(t.parameters for t in list_tools() if t.name == "ken_find")
    assert schema["properties"]["response_format"]["enum"] == ["legacy", "evidence"]
    assert schema["properties"]["response_format"]["default"] == "legacy"


def test_preparation_command_builds_profile_used_by_public_search(tmp_path, monkeypatch, capsys):
    from ken.cli import main
    root = tmp_path / "project"
    root.mkdir()
    (root / "code.py").write_text("def normalize(value):\n    return value.lower()\n")
    spec = EncoderSpec("test/provided", "d" * 40, "provided")
    profile = RetrievalProfile(spec, spec)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile.to_dict()))
    monkeypatch.setattr("ken.retrieval.representations.load_encoder", lambda spec: Encoder())
    assert main(["retrieval", "index", "--path", str(root), "--profile", str(path), "--json"]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["profile_version"] == profile.fingerprint
    assert prepared["passages"] > 0
    assert main(["search-symbols", "Where is `normalize` defined?", "--path", str(root),
                 "--response-format", "evidence", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["profile_version"] == prepared["profile_version"]
    assert found["results"][0]["entity"]["qualname"] == "normalize"


def test_real_stdio_mcp_preserves_evidence_response_across_repeated_calls(tmp_path, monkeypatch):
    import asyncio
    import sys
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from ken.retrieval.public import find
    project(tmp_path, monkeypatch)
    query = "Where is `redirect` defined?"
    with connect(_paths.db_path(tmp_path)) as conn:
        expected = find(conn, tmp_path, query)
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ken", "mcp", str(tmp_path)])
        with (tmp_path / "mcp-stderr.log").open("w") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for _ in range(2):
                        result = await session.call_tool("ken_find", {"query": query, "scope": "symbols",
                            "response_format": "evidence"}, read_timeout_seconds=10)
                        assert not result.is_error
                        payload = result.structured_content
                        if payload is None:
                            assert len(result.content) == 1 and result.content[0].type == "text"
                            payload = json.loads(result.content[0].text)
                        assert payload == expected
    asyncio.run(exercise())
