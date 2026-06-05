"""Tests for the parser-dependent tools: callgraph, wiring, type_hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest

from ken.codeflow import callgraph, type_hierarchy, wiring
from ken.db import connect, init_schema
from ken.indexer import index_files


@pytest.fixture
def project(tmp_path):
    root = tmp_path
    (root / ".ken").mkdir()
    conn = connect(root / ".ken" / "ken.db")
    init_schema(conn)
    yield root, conn
    conn.close()


def _write_and_index(root, conn, files: dict[str, str]):
    rels = []
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        rels.append(Path(rel))
    index_files(conn, root, rels)


# --- callgraph --------------------------------------------------------------


def test_callgraph_same_file_callees(project):
    root, conn = project
    _write_and_index(root, conn, {
        "m.py": (
            "def helper():\n    return 1\n\n"
            "def main():\n    x = helper()\n    return helper()\n"
        ),
    })
    res = callgraph(conn, "main", direction="callees", project_root=root)
    assert res["ok"]
    callees = {e["to_qualname"]: e for e in res["callees"]}
    assert "helper" in callees
    assert callees["helper"]["confidence_tier"] == "T1"


def test_callgraph_cross_file_callers_via_import(project):
    root, conn = project
    _write_and_index(root, conn, {
        "lib.py": "def process():\n    return 1\n",
        "app.py": "import lib\n\ndef run():\n    return lib.process()\n",
    })
    res = callgraph(conn, "process", direction="callers", project_root=root)
    assert res["ok"]
    callers = {c["from_qualname"]: c for c in res["callers"]}
    assert "run" in callers
    assert callers["run"]["confidence_tier"] in ("T1", "T2")


def test_callgraph_unsupported_symbol(project):
    root, conn = project
    _write_and_index(root, conn, {"m.py": "def a():\n    return 1\n"})
    res = callgraph(conn, "does_not_exist", project_root=root)
    assert res["ok"] is False


# --- wiring -----------------------------------------------------------------


def test_wiring_extracts_route_and_env(project):
    root, conn = project
    _write_and_index(root, conn, {
        "api.py": (
            "import os\n\n"
            "@app.route('/users/{id}')\n"
            "def get_user():\n"
            "    token = os.environ['KEN_TOKEN']\n"
            "    return token\n"
        ),
    })
    res = wiring(conn, project_root=root)
    assert res["ok"]
    kinds = {(w["kind"], w["trigger"]) for w in res["wiring"]}
    assert ("route", "/users/{id}") in kinds
    assert ("env", "KEN_TOKEN") in kinds
    route = next(w for w in res["wiring"] if w["kind"] == "route")
    assert route["handler_qualname"] == "get_user"


def test_wiring_filter_by_kind(project):
    root, conn = project
    _write_and_index(root, conn, {
        "api.py": "@app.route('/x')\ndef h():\n    return 1\n",
    })
    res = wiring(conn, trigger_kind="route", project_root=root)
    assert all(w["kind"] == "route" for w in res["wiring"])
    assert len(res["wiring"]) == 1


# --- type_hierarchy ---------------------------------------------------------


def test_type_hierarchy_subclasses_and_overrides(project):
    root, conn = project
    _write_and_index(root, conn, {
        "base.py": "class Animal:\n    def speak(self):\n        return ''\n",
        "dog.py": (
            "from base import Animal\n\n"
            "class Dog(Animal):\n    def speak(self):\n        return 'woof'\n"
        ),
        "puppy.py": "from dog import Dog\n\nclass Puppy(Dog):\n    pass\n",
    })
    res = type_hierarchy(conn, "Animal", direction="sub", project_root=root)
    assert res["ok"]
    assert set(res["descendants"]) == {"Dog", "Puppy"}
    overrides = {o["class"]: o["overrides"] for o in res["overrides"]}
    assert "speak" in overrides.get("Dog", [])


def test_type_hierarchy_ancestors_keeps_external_base(project):
    root, conn = project
    _write_and_index(root, conn, {
        "model.py": "class User(BaseModel):\n    name = 1\n",
    })
    res = type_hierarchy(conn, "User", direction="super", project_root=root)
    assert res["ok"]
    assert "BaseModel" in res["ancestors"]


# --- multi-language (any tree-sitter language) ------------------------------


def test_callgraph_typescript_cross_file_callers(project):
    root, conn = project
    _write_and_index(root, conn, {
        "lib.ts": "export function process() { return 1 }\n",
        "app.ts": (
            "import { process } from './lib'\n"
            "function run() { return process() }\n"
        ),
    })
    res = callgraph(conn, "process", direction="callers", project_root=root)
    assert res["ok"]
    assert any(c["from_qualname"] == "run" for c in res["callers"])


def test_type_hierarchy_typescript_subclasses(project):
    root, conn = project
    _write_and_index(root, conn, {
        "base.ts": "export class Base {}\n",
        "derived.ts": "import { Base } from './base'\nclass Derived extends Base {}\n",
    })
    res = type_hierarchy(conn, "Base", direction="sub", project_root=root)
    assert res["ok"]
    assert "Derived" in res["descendants"]


def test_callgraph_go_callees(project):
    root, conn = project
    _write_and_index(root, conn, {
        "util.go": "package m\nfunc Helper() int { return 1 }\n",
        "main.go": "package m\nfunc Run() int { return Helper() }\n",
    })
    res = callgraph(conn, "Run", direction="callees", project_root=root)
    assert res["ok"]
    assert any(e["to_qualname"] == "Helper" for e in res["callees"])


def test_type_hierarchy_java_overrides(project):
    root, conn = project
    _write_and_index(root, conn, {
        "Animal.java": "class Animal { void speak(){} }\n",
        "Dog.java": "class Dog extends Animal { void speak(){} }\n",
    })
    res = type_hierarchy(conn, "Animal", direction="sub", project_root=root)
    assert res["ok"]
    assert "Dog" in res["descendants"]
    assert any("speak" in o["overrides"] for o in res["overrides"])


def test_wiring_nestjs_route(project):
    root, conn = project
    _write_and_index(root, conn, {
        "ctrl.ts": "class C {\n  @Get('/users')\n  handle() { return 1 }\n}\n",
    })
    res = wiring(conn, trigger_kind="route", project_root=root)
    assert res["ok"]
    routes = {w["trigger"]: w for w in res["wiring"]}
    assert "/users" in routes
    assert routes["/users"]["handler_qualname"] == "C.handle"
