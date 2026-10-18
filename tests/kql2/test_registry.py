"""Persistent KQL2 modules live with project knowledge, independently of caches."""

import sqlite3

import pytest

from ken.kql2.registry import ModuleRegistry


SOURCE = '''language "kql/2"; module project.saved;
pattern HasClose(in TypeDecl $owner) {
  class $owner {method $method {name:"close";}}
}
query one {select 1;}
'''


def test_modules_persist_in_main_ken_database(tmp_path):
    saved = ModuleRegistry(tmp_path).save(SOURCE, description="Saved conventions")
    loaded = ModuleRegistry(tmp_path).get("project.saved")
    assert loaded == saved
    assert loaded.source == SOURCE
    assert loaded.description == "Saved conventions"
    assert loaded.queries == ("one",)
    assert loaded.patterns == ("HasClose",)
    with sqlite3.connect(tmp_path / ".ken/ken.db") as db:
        assert db.execute("SELECT source FROM kql_modules WHERE module=?",
                          ("project.saved",)).fetchone()[0] == SOURCE
    assert not (tmp_path / ".ken/structural").exists()


def test_reading_absent_registry_does_not_create_database(tmp_path):
    registry = ModuleRegistry(tmp_path)
    assert registry.list_modules() == []
    with pytest.raises(ValueError, match="not found"):
        registry.get("project.missing")
    assert not (tmp_path / ".ken").exists()


def test_save_is_idempotent_but_updates_require_current_revision(tmp_path):
    registry = ModuleRegistry(tmp_path)
    before = registry.save(SOURCE)
    assert registry.save(SOURCE) == before
    changed = SOURCE.replace("select 1", "select 2")
    with pytest.raises(ValueError, match="revision"):
        registry.save(changed)
    after = registry.save(changed, expected_revision=before.revision)
    assert after.revision != before.revision
    with pytest.raises(ValueError, match="revision"):
        registry.save(SOURCE, expected_revision=before.revision)
    assert registry.get("project.saved") == after


def test_delete_checks_revision_and_preserves_other_modules(tmp_path):
    registry = ModuleRegistry(tmp_path)
    saved = registry.save(SOURCE)
    other = registry.save(SOURCE.replace("project.saved", "project.other"))
    with pytest.raises(ValueError, match="revision"):
        registry.delete("project.saved", expected_revision="old")
    registry.delete("project.saved", expected_revision=saved.revision)
    assert registry.list_modules() == [other]
    with pytest.raises(ValueError, match="not found"):
        registry.get("project.saved")


def test_registry_is_additive_to_existing_knowledge_database(tmp_path):
    directory = tmp_path / ".ken"
    directory.mkdir()
    with sqlite3.connect(directory / "ken.db") as db:
        db.execute("CREATE TABLE existing_knowledge(topic TEXT)")
        db.execute("INSERT INTO existing_knowledge VALUES ('keep')")
    ModuleRegistry(tmp_path).save(SOURCE)
    with sqlite3.connect(directory / "ken.db") as db:
        assert db.execute("SELECT topic FROM existing_knowledge").fetchall() == [("keep",)]


@pytest.mark.parametrize("source", ["not KQL", 'language "kql/2"; module ken.core; query q {select 1;}'])
def test_invalid_or_reserved_modules_do_not_write(tmp_path, source):
    with pytest.raises(ValueError):
        ModuleRegistry(tmp_path).save(source)
    assert not (tmp_path / ".ken").exists()


def test_missing_import_does_not_create_or_partially_update_registry(tmp_path):
    registry = ModuleRegistry(tmp_path)
    missing = SOURCE.replace("module project.saved;", "module project.saved; import project.missing;")
    with pytest.raises(ValueError, match="missing.*project.missing"):
        registry.save(missing)
    assert not (tmp_path / ".ken").exists()
    before = registry.save(SOURCE)
    with pytest.raises(ValueError, match="missing.*project.missing"):
        registry.save(missing, expected_revision=before.revision)
    assert registry.get(before.module) == before


def test_imported_modules_cannot_be_deleted(tmp_path):
    registry = ModuleRegistry(tmp_path)
    dependency = registry.save(SOURCE)
    registry.save('language "kql/2"; module project.client; import project.saved; query q {select 2;}')
    with pytest.raises(ValueError, match="imported.*project.client"):
        registry.delete(dependency.module)
    assert registry.get(dependency.module) == dependency
