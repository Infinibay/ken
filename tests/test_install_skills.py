"""Skills are usable package resources with a non-destructive project lifecycle."""

from __future__ import annotations

import json

import pytest

from ken.cli import main
from ken.gitignore_filter import iter_files
from ken.install_uninstall import uninstall
from ken.skills.catalog import bundled_skills
from ken.skills.installation import install_skills, uninstall_skills
from ken.skills.ownership import MANIFEST, digest


@pytest.mark.parametrize(
    "flags, destinations",
    [
        ([], [".claude/skills"]),
        (["--codex"], [".agents/skills"]),
        (["--opencode"], [".opencode/skills"]),
        (["--deepseek"], [".dsh/skills"]),
        (["--codex", "--deepseek"], [".agents/skills"]),
        (
            ["--claude", "--codex", "--opencode", "--deepseek"],
            [".claude/skills", ".agents/skills"],
        ),
    ],
)
def test_cli_installs_complete_bundles_and_uninstalls(
    tmp_path, flags, destinations, capsys
):
    assert main(["install", str(tmp_path), *flags]) == 0
    output = capsys.readouterr().out
    if "--codex" in flags and "--deepseek" in flags:
        assert "[skills] Codex and DeepSeek share .agents/skills" in output
    bundles = bundled_skills()
    assert len(bundles) == 8
    for destination in destinations:
        assert f"[skills] 8 skills at {tmp_path / destination}" in output
        for name, resources in bundles.items():
            for relative, content in resources.items():
                assert (
                    tmp_path / destination / name / relative
                ).read_bytes() == content
    assert len(json.loads((tmp_path / MANIFEST).read_text())["skills"]) == 8 * len(
        destinations
    )
    assert main(["install", str(tmp_path), *flags]) == 0
    output = capsys.readouterr().out
    assert "unchanged=" + str(8 * len(destinations)) in output
    for destination in destinations:
        assert f"[skills] 8 skills at {tmp_path / destination}" in output
    assert uninstall(tmp_path, keep_db=False) == 0
    for destination in destinations:
        assert not list((tmp_path / destination).glob("*/SKILL.md"))


def test_no_wire_skips_all_skill_and_host_configuration(tmp_path):
    assert (
        main(
            ["install", str(tmp_path), "--codex", "--deepseek", "--no-wire", "--quiet"]
        )
        == 0
    )
    for relative in [".agents", ".claude", ".codex", ".dsh", MANIFEST]:
        assert not (tmp_path / relative).exists()


def test_installed_examples_are_excluded_but_project_notes_and_bundled_sources_remain(
    tmp_path,
):
    install_skills(tmp_path, claude=True, codex=True, opencode=True, deepseek=True)
    install_skills(tmp_path, opencode=True, deepseek=True)
    note = tmp_path / ".agents/notes/architecture.md"
    note.parent.mkdir(parents=True)
    note.write_text("Project architecture")
    source = tmp_path / "src/skills/bundled/example.md"
    source.parent.mkdir(parents=True)
    source.write_text("Product resource")
    assert set(iter_files(tmp_path)) == {
        note.relative_to(tmp_path),
        source.relative_to(tmp_path),
    }


def test_reinstall_updates_owned_bundle_and_removes_retired_reference(
    tmp_path, monkeypatch
):
    first = install_skills(tmp_path, codex=True)
    assert len(first.installed) == 8
    assert len(install_skills(tmp_path, codex=True).unchanged) == 8
    bundles = bundled_skills()
    resources = bundles["ken-prevent-regressions"]
    del resources["references/return-contract.json"]
    resources["SKILL.md"] += b"\nUpdated guidance.\n"
    resources["references/new.json"] = b"{}\n"
    monkeypatch.setattr("ken.skills.installation.bundled_skills", lambda: bundles)
    result = install_skills(tmp_path, codex=True)
    target = ".agents/skills/ken-prevent-regressions"
    assert result.updated == [target]
    assert not (tmp_path / target / "references/return-contract.json").exists()
    assert (tmp_path / target / "references/new.json").read_bytes() == b"{}\n"


@pytest.mark.parametrize("edited", ["SKILL.md", "references/return-contract.json"])
def test_local_edit_preserves_entire_bundle_on_update_and_uninstall(tmp_path, edited):
    install_skills(tmp_path, codex=True)
    target = ".agents/skills/ken-prevent-regressions"
    path = tmp_path / target / edited
    path.write_text("Local customization\n")
    assert target in install_skills(tmp_path, codex=True).preserved
    result = uninstall_skills(tmp_path)
    assert target in result.preserved
    assert path.read_text() == "Local customization\n"
    assert (tmp_path / target / "SKILL.md").exists()
    assert (tmp_path / target / "references/return-contract.json").exists()
    assert len(result.removed) == 7


def test_unowned_identical_skill_is_never_adopted(tmp_path):
    target = ".agents/skills/ken-locate-code"
    path = tmp_path / target / "SKILL.md"
    path.parent.mkdir(parents=True)
    original = bundled_skills()["ken-locate-code"]["SKILL.md"]
    path.write_bytes(original)
    assert target in install_skills(tmp_path, codex=True).preserved
    uninstall_skills(tmp_path)
    assert path.read_bytes() == original


def test_extra_user_file_survives_removal(tmp_path):
    install_skills(tmp_path, codex=True)
    note = tmp_path / ".agents/skills/ken-locate-code/my-notes.txt"
    note.write_text("Keep this")
    uninstall_skills(tmp_path)
    assert note.read_text() == "Keep this"
    assert not (note.parent / "SKILL.md").exists()


@pytest.mark.parametrize(
    "location", [".agents", ".agents/skills", ".agents/skills/ken-locate-code"]
)
def test_install_does_not_follow_skill_symlinks(tmp_path, location):
    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / location
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    result = install_skills(root, codex=True)
    assert result.preserved
    assert list(outside.iterdir()) == []


def test_replaced_resource_symlink_is_preserved(tmp_path):
    install_skills(tmp_path, codex=True)
    path = tmp_path / ".agents/skills/ken-locate-code/SKILL.md"
    outside = tmp_path / "outside.md"
    outside.write_text("Keep")
    path.unlink()
    path.symlink_to(outside)
    assert uninstall_skills(tmp_path).preserved
    assert outside.read_text() == "Keep"


@pytest.mark.parametrize(
    "target",
    ["../../outside", ".agents/skills/../../../outside", ".agents/skills/user-skill"],
)
def test_manifest_cannot_claim_arbitrary_files(tmp_path, target):
    path = tmp_path / MANIFEST
    path.parent.mkdir()
    path.write_text(
        json.dumps({"version": 1, "skills": {target: {"SKILL.md": digest(b"text")}}})
    )
    with pytest.raises(ValueError, match="Invalid"):
        uninstall_skills(tmp_path)


def test_corrupt_manifest_stops_without_overwriting_existing_skills(tmp_path):
    install_skills(tmp_path, codex=True)
    (tmp_path / MANIFEST).write_text("broken")
    with pytest.raises(ValueError, match="Invalid"):
        install_skills(tmp_path, codex=True)
    assert len(list((tmp_path / ".agents/skills").glob("*/SKILL.md"))) == 8
