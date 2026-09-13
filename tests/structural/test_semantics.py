from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.model import IR
from ken.structural.semantic import link_project
from ken.structural.query import evaluate_pattern
from .examples import MULTILINGUAL


def build(source, language="python", path="a.py"):
    return link_project([lower_source(source, language, path)])


def facts(graph, relation):
    return [f for f in graph.facts if f.relation == relation]


def test_local_variables_do_not_unify_across_functions_or_files():
    units = [lower_source('def a(x):\n y = x\n return y\ndef b(x):\n y = x\n return y\n', "python", p) for p in ["one.py", "two.py"]]
    g = link_project(units)
    assert len([e for e in g.entities.values() if e.name == "y"]) == 4
    for f in facts(g, "ASSIGNED_FROM"):
        assert g.entities[f.subject].path == g.entities[f.object].path
        assert f.subject.rsplit("/", 1)[0] == f.object.rsplit("/", 1)[0]


def test_nested_function_is_not_promoted_to_class_method():
    g = build('class A:\n def outer(self):\n  def inner(): return 1\n  return inner()\n')
    assert [f.attrs["name"] for f in facts(g, "HAS_METHOD")] == ["outer"]
    assert len(facts(g, "CALLS")) == 1


def test_same_name_overloads_remain_distinct():
    g = build('class C { int f(int x) { return x; } String f(String x) { return x; } }', "java", "a.java")
    methods = facts(g, "HAS_METHOD")
    assert len(methods) == 2
    assert len({f.object for f in methods}) == 2


def test_python_import_alias_resolves_cross_file_allocation():
    units = [lower_source('class Product: pass', "python", "models.py"),
             lower_source('from models import Product as P\ndef make(): return P()', "python", "factory.py")]
    g = link_project(units)
    assert len(facts(g, "ALLOCATES_TYPE")) == 1
    assert g.entities[facts(g, "ALLOCATES_TYPE")[0].object].path == "models.py"


def test_unimported_unique_cross_file_name_does_not_resolve():
    g = link_project([lower_source('class Product: pass', "python", "models.py"),
                      lower_source('def make(): return Product()', "python", "factory.py")])
    assert not facts(g, "ALLOCATES_TYPE")


def test_python_relative_imports_resolve_package_siblings():
    g = link_project([lower_source('class Product: pass', "python", "pkg/models.py"),
                      lower_source('from .models import Product\ndef make(): return Product()', "python", "pkg/factory.py")])
    assert facts(g, "ALLOCATES_TYPE")


@pytest.mark.parametrize("language,extension", [("javascript", ".js"), ("typescript", ".ts")])
def test_js_ts_named_import_aliases(language, extension):
    g = link_project([lower_source('export class Product {}', language, "models"+extension),
                      lower_source('import { Product as P } from "./models"; export function make() { return new P(); }', language, "factory"+extension)])
    assert facts(g, "ALLOCATES_TYPE")


def test_call_arguments_and_returns_form_interprocedural_flow():
    g = build('def identity(value):\n return value\ndef caller(argument):\n result = identity(argument)\n return result\n')
    assert len(facts(g, "BINDS_TO")) == 1
    assert len(facts(g, "CALLS")) == 1
    query = 'parameter(name: argument) as $input; variable(name: result) as $output;\nrequire $input FLOWS_TO{2,4} $output'
    assert evaluate_pattern(g, query).matches


def test_spreads_preserve_uncertain_argument_binding():
    g = build('def target(a, b): return a\ndef call(values): return target(*values)\n')
    assert not facts(g, "BINDS_TO")
    assert len(facts(g, "MAY_BIND_TO")) == 2
    assert facts(g, "ARGUMENT")[0].attrs["kind"] == "spread_positional"


def test_python_parameter_kinds_and_defaults():
    g = build('def f(a, /, b=1, *args, c: str="x", **kwargs):\n yield from args\n')
    parameters = facts(g, "HAS_PARAMETER")
    assert [f.attrs["kind"] for f in parameters] == ["positional_only", "positional", "variadic_positional", "keyword_only", "variadic_keyword"]
    yields = [op for op in g.operations if op.kind == "YIELD"]
    assert yields[0].attrs["delegated"]


@pytest.mark.parametrize("language", ["javascript", "typescript"])
def test_generator_delegation_import_export_and_rest_are_retained(language):
    extension, source = MULTILINGUAL[language]
    g = build(source + '\nfunction f(...args) { return call(...args); }', language, "a"+extension)
    assert facts(g, "HAS_EXPORT")
    assert any(op.kind == "YIELD" and op.attrs["delegated"] for op in g.operations)
    assert any(f.attrs["kind"] == "spread_positional" for f in facts(g, "ARGUMENT"))
    assert any(f.attrs["kind"] == "variadic_positional" for f in facts(g, "HAS_PARAMETER"))


def test_async_await_and_resource_scopes_remain_explicit():
    g = build('async def f(resource):\n async with resource:\n  await task()\n  yield 1\n')
    assert facts(g, "HAS_AWAIT") and facts(g, "HAS_YIELD") and facts(g, "HAS_RESOURCE_SCOPE")


@pytest.mark.parametrize("language", sorted(MULTILINGUAL))
def test_ir_serialization_roundtrip_preserves_native_syntax(language):
    extension, source = MULTILINGUAL[language]
    ir = lower_source(source, language, "a"+extension)
    assert IR.from_dict(ir.to_dict()).to_dict() == ir.to_dict()
    assert all(op.native_kind for op in ir.operations)
    assert any(op.attrs.get("tokens") for op in ir.operations)


def test_unsupported_language_is_not_silently_normalized():
    with pytest.raises(ValueError, match="unavailable"):
        lower_source("module x", "haskell")


def test_malformed_source_has_diagnostics_and_incomplete_capability():
    ir = lower_source('def broken(:\n return value', 'python', 'bad.py')
    assert ir.diagnostics
    assert "declarations" not in ir.capabilities


@pytest.mark.parametrize("imports,constructor", [('import threading','threading.Thread'), ('import threading as th','th.Thread'), ('from threading import Thread as T','T')])
def test_thread_creation_start_join_and_entry(imports, constructor):
    g = build(f'{imports}\ndef work(): pass\ndef run():\n t = {constructor}(target=work)\n t.start()\n t.join()\n')
    assert len(facts(g, "CREATES_CONTEXT")) == 1
    assert len(facts(g, "CONTEXT_ENTRY")) == 1
    assert len(facts(g, "STARTS_CONTEXT")) == 1
    assert len(facts(g, "WAITS_FOR")) == 1


def test_unrelated_start_is_not_a_thread():
    g = build('class Service:\n def start(self): pass\ns = Service()\ns.start()\n')
    assert not facts(g, "STARTS_CONTEXT")


def test_timed_join_is_not_a_proven_wait_for_completion():
    g = build('import threading\nt = threading.Thread()\nt.join(0.1)\n')
    assert not facts(g, "WAITS_FOR")
    assert facts(g, "MAY_WAITS_FOR")


def test_shadowed_threading_alias_does_not_activate_api_model():
    g = build('import threading\ndef run(threading):\n t = threading.Thread()\n t.start()\n')
    assert not facts(g, "CREATES_CONTEXT")


def test_asyncio_task_has_explicit_entry():
    g = build('import asyncio\nasync def work(): pass\nasync def run():\n t = asyncio.create_task(work())\n await t\n')
    assert facts(g, "CREATES_CONTEXT") and facts(g, "STARTS_CONTEXT") and facts(g, "CONTEXT_ENTRY")


def test_go_goroutine_is_an_explicit_spawn():
    suffix, source = MULTILINGUAL["go"]
    assert facts(build(source,"go","a"+suffix), "SPAWNS_CONTEXT")


def test_parameter_shadowing_class_name_does_not_create_false_allocation():
    g = build('class Product: pass\ndef make(Product): return Product()\n')
    assert not facts(g, "ALLOCATES_TYPE")


def test_relinking_does_not_mutate_cached_unit_entities():
    unit = lower_source('def f(x: int): return x', 'python', 'a.py')
    original = unit.to_dict()
    assert link_project([unit]).to_dict() == link_project([unit]).to_dict()
    assert unit.to_dict() == original


def test_imported_factory_is_connected_to_its_consumer():
    graph = link_project([
        lower_source('class Product: pass\ndef make(): return Product()', "python", "factory.py"),
        lower_source('from factory import make\ndef use():\n product = make()\n return product', "python", "consumer.py"),
    ])
    query = 'require $factory RETURNS_NEW $type\nrequire $call TARGET $factory\nrequire $call FLOWS_TO $consumer'
    assert evaluate_pattern(graph, query).matches


def test_unexported_js_symbol_is_not_resolved_by_named_import():
    graph = link_project([
        lower_source('class Hidden {}', "javascript", "hidden.js"),
        lower_source('import { Hidden } from "./hidden"; function make() { return new Hidden(); }', "javascript", "factory.js"),
    ])
    assert not facts(graph, "ALLOCATES_TYPE")


def test_reassigned_imported_thread_constructor_is_not_treated_as_thread():
    graph = build('from threading import Thread as T\nT = other\nt = T()\nt.start()\n')
    assert not facts(graph, "CREATES_CONTEXT")
