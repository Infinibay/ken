"""`ken mcp` startup guards.

The MCP server imports ``mcp.server.MCPServer``, which only exists in the
``mcp`` Python SDK v2. Older ken-rank releases (0.10.0 on PyPI, with the
wrong ``mcp>=1.0`` pin) could resolve to mcp 1.x, and then ``ken mcp``
would crash at import with a raw ``ImportError`` — the assistant would
detect the MCP server as "failing" because the handshake produced no
output.

The guard in ``ken.mcp.server`` catches that import failure and writes
a clear remediation message before exiting with status 1. This file
exercises that path by stubbing the ``mcp.server`` import to raise.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from unittest.mock import patch

import pytest


def test_mcp_server_exits_with_remediation_when_mcpserver_missing(capsys):
    """A broken ``mcp`` install must produce an actionable error, not a traceback."""

    saved = sys.modules.get("ken.mcp.server")
    # Drop any cached version so the patched import actually runs.
    sys.modules.pop("ken.mcp.server", None)

    real_import = builtins.__import__

    def _raise(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mcp.server" or name.startswith("mcp.server."):
            raise ImportError(
                "cannot import name 'MCPServer' from 'mcp.server' (stubbed); "
                "did you mean 'FastMCP'?"
            )
        return real_import(name, globals, locals, fromlist, level)

    try:
        with patch.object(builtins, "__import__", side_effect=_raise):
            with pytest.raises(SystemExit) as exc_info:
                importlib.import_module("ken.mcp.server")

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "this build of ken needs the `mcp` Python SDK >= 2.0" in err
        assert "uv tool install --reinstall ken-rank" in err
        # And it must NOT include the raw Python traceback — that's the
        # whole point of the guard.
        assert "Traceback (most recent call last)" not in err
    finally:
        # Always restore the real module so we don't poison later tests.
        sys.modules.pop("ken.mcp.server", None)
        if saved is not None:
            sys.modules["ken.mcp.server"] = saved
