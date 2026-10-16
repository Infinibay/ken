"""Owned instruction installation is optional and preserves project content."""
import io
import json
import pytest
from ken.cli import main


def test_explicit_install_preserves_original_prefix_and_is_idempotent(tmp_path):
    from ken.project_instructions import configure_instructions
    original = b"# Team rules\r\nKeep this exactly.\r\n"
    target = tmp_path / "AGENTS.md"
    target.write_bytes(original)
    configure_instructions(tmp_path, choice=True)
    installed = target.read_bytes()
    assert installed.startswith(original)
    assert b"English" in installed
    assert installed.count(b"<!-- ken:instructions:start -->") == 1
    configure_instructions(tmp_path, choice=True)
    assert target.read_bytes() == installed


def test_decline_and_noninteractive_default_never_create_instructions(tmp_path, monkeypatch):
    from ken.project_instructions import configure_instructions
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    configure_instructions(tmp_path)
    configure_instructions(tmp_path, choice=False)
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".ken/instructions.json").exists()


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("answer, installed", [("\n", True), ("y\n", True), ("n\n", False), ("", False)])
def test_interactive_default_yes_and_decline(tmp_path, monkeypatch, capsys, answer, installed):
    from ken.project_instructions import configure_instructions
    monkeypatch.setattr("sys.stdin", Terminal(answer))
    configure_instructions(tmp_path)
    assert (tmp_path / "AGENTS.md").exists() is installed
    assert "[Y/n]" in capsys.readouterr().out


def test_local_edits_and_unmanaged_recommended_block_are_preserved(tmp_path):
    from ken.project_instructions import configure_instructions
    configure_instructions(tmp_path, choice=True)
    target = tmp_path / "AGENTS.md"
    customized = target.read_text().replace("English", "the project language")
    target.write_text(customized)
    configure_instructions(tmp_path, choice=True)
    assert target.read_text() == customized
    target.write_text("## Code intelligence: ken\nMy own guidance.\n")
    configure_instructions(tmp_path, choice=True)
    assert target.read_text() == "## Code intelligence: ken\nMy own guidance.\n"


def test_claude_import_preserves_content_and_does_not_duplicate_an_existing_import(tmp_path):
    from ken.project_instructions import configure_instructions
    target = tmp_path / "CLAUDE.md"
    target.write_text("# Claude rules\nBe concise.\n")
    configure_instructions(tmp_path, choice=True, claude=True)
    assert target.read_text().startswith("# Claude rules\nBe concise.\n")
    assert target.read_text().count("@AGENTS.md") == 1
    configure_instructions(tmp_path, choice=True, claude=True)
    assert target.read_text().count("@AGENTS.md") == 1


def test_symlinked_instruction_file_is_never_followed(tmp_path):
    from ken.project_instructions import configure_instructions
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Keep")
    (root / "AGENTS.md").symlink_to(outside)
    configure_instructions(root, choice=True)
    assert outside.read_text() == "Keep"
    assert (root / "AGENTS.md").is_symlink()


def test_uninstall_removes_only_unchanged_owned_blocks(tmp_path):
    from ken.project_instructions import configure_instructions, remove_instructions
    target = tmp_path / "AGENTS.md"
    target.write_text("# Team rules\nKeep.\n")
    configure_instructions(tmp_path, choice=True, claude=True)
    remove_instructions(tmp_path)
    assert target.read_text().startswith("# Team rules\nKeep.\n")
    assert "ken:instructions" not in target.read_text()
    assert not (tmp_path / "CLAUDE.md").exists()
    configure_instructions(tmp_path, choice=True)
    edited = target.read_text().replace("English", "our language")
    target.write_text(edited)
    remove_instructions(tmp_path)
    assert target.read_text() == edited


def test_cli_choice_and_no_wire_contract(tmp_path):
    project = tmp_path / "enabled"
    project.mkdir()
    assert main(["install", str(project), "--codex", "--agents-md", "--quiet"]) == 0
    assert (project / "AGENTS.md").is_file()
    assert main(["uninstall", str(project)]) == 0
    assert not (project / "AGENTS.md").exists()
    bare = tmp_path / "bare"
    bare.mkdir()
    assert main(["install", str(bare), "--agents-md", "--no-wire", "--quiet"]) == 0
    assert not (bare / "AGENTS.md").exists()
