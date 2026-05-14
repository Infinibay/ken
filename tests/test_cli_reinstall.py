"""CLI reinstall command."""

from __future__ import annotations

import subprocess

from ken.cli import main


def test_reinstall_cli_reinstalls_tool_and_project(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        "ken.cli.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"uv", "ken"} else None,
    )

    def fake_run(cmd, *, check, stdout=None, stderr=None):
        calls.append((cmd, check, stdout, stderr))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("ken.cli.subprocess.run", fake_run)

    rc = main(["reinstall", str(tmp_path), "--codex", "--embed", "--embed-limit", "7"])

    assert rc == 0
    assert calls[0][0][:4] == ["/usr/bin/uv", "tool", "install", "--editable"]
    assert calls[0][0][-3:] == ["--force", "--reinstall", "--refresh"]
    assert calls[1][0] == [
        "/usr/bin/ken",
        "install",
        str(tmp_path),
        "--codex",
        "--embed",
        "--embed-limit",
        "7",
    ]


def test_reinstall_cli_can_skip_project_install(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "ken.cli.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "uv" else None,
    )
    monkeypatch.setattr(
        "ken.cli.subprocess.run",
        lambda cmd, *, check, stdout=None, stderr=None: calls.append(cmd)
        or subprocess.CompletedProcess(cmd, 0),
    )

    rc = main(["reinstall", str(tmp_path), "--no-project"])

    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0:3] == ["/usr/bin/uv", "tool", "install"]


def test_reinstall_cli_reports_missing_uv(monkeypatch, capsys):
    monkeypatch.setattr("ken.cli.shutil.which", lambda _name: None)

    rc = main(["reinstall", "--no-project"])

    assert rc == 1
    assert "uv is required" in capsys.readouterr().err
