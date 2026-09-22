"""Project linking. Only lexical declarations and explicit imports resolve names.

Types are possible values, not proof of runtime dispatch. Resolved evidence is
kept separate from syntax, and rebuilt after every project content change.
"""
from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from pathlib import PurePosixPath

from .model import Entity, Fact, IR

PRIMITIVES = {"string": "str", "String": "str", "str": "str", "int": "int", "Int": "int", "i32": "int",
              "i64": "int", "int32": "int", "int64": "int", "number": "number", "float": "float",
              "double": "float", "bool": "bool", "boolean": "bool", "Boolean": "bool", "void": "void",
              "None": "none", "NoneType": "none", "any": "unknown", "Any": "unknown", "object": "unknown"}


def normalized_type(annotation: str) -> str:
    annotation = annotation.strip(": &*?'").removeprefix("mut ")
    return PRIMITIVES.get(annotation, annotation or "unknown")


# Rust spells ownership where the other languages spell a pointer: ``Box<Expr>``,
# ``Rc<Expr>`` and ``Arc<Expr>`` all denote an ``Expr`` for the purposes of "this
# field is typed by that type". ``normalized_type`` strips ``&``/``*`` but knows no
# language, so a user type genuinely called ``Box<T>`` in another language must not
# be unwrapped: the caller applies this only when the entity is Rust.
RUST_SMART_POINTER = re.compile(r"^(?:Box|Rc|Arc)\s*<\s*(.+?)\s*>$")


def rust_denoted_type(spelling: str) -> str:
    """The type a Rust annotation denotes, unwrapping a smart pointer once."""
    pointer = RUST_SMART_POINTER.fullmatch(spelling.strip())
    if pointer is None:
        return spelling
    return re.sub(r"^(?:dyn|impl)\s+", "", pointer[1].strip())


def link_project(units: list[IR], *, copy_entities: bool = True) -> IR:
    """Link units, isolating their mutable entity metadata by default.

    A caller that owns disposable units may transfer their entities with
    ``copy_entities=False``. Those units must not be reused after linking.
    """
    graph = IR("<project>", "mixed")
    graph.capabilities = set.intersection(*(u.capabilities for u in units)) if units else set()
    for unit in units:
        from copy import deepcopy
        graph.entities.update(deepcopy(unit.entities) if copy_entities else unit.entities)
        graph.operations.extend(unit.operations)
        graph.facts.extend(unit.facts)
        graph.diagnostics.extend(unit.diagnostics)
    entities = graph.entities
    by_relation: dict[str, list[Fact]] = defaultdict(list)
    for f in graph.facts:
        by_relation[f.relation].append(f)
    types = {e.id: e for e in entities.values() if e.kind in {"CLASS", "INTERFACE"}}
    class_names: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in types.values():
        if not e.attrs.get('expression'):
            class_names[(e.path, e.name)].append(e.id)
    paths = {u.path for u in units}
    imports: dict[tuple[str, str], tuple[str, str]] = {}
    module_imports: dict[tuple[str, str], set[str]] = defaultdict(set)
    ambiguous_imports: set[tuple[str, str]] = set()
    import_origins: dict[tuple[str, str], set[tuple[str, ...]]] = defaultdict(set)
    import_options: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    module_declarations = {(e.path, e.name) for e in entities.values()
                           if e.id.rsplit('/', 1)[0] == e.path + '::module'
                           and e.kind in {'CALLABLE', 'CLASS', 'STORAGE'}}
    exported: dict[tuple[str, str], str] = {}
    java_packages = {u.path: u.entities[u.path + "::module"].attrs.get("package", "")
                     for u in units if u.language == "java"}
    java_types: dict[str, list[str]] = defaultdict(list)
    for e in types.values():
        if e.path in java_packages and e.id.rsplit("/", 1)[0] == e.path + "::module":
            java_types[".".join(filter(None, [java_packages[e.path], e.name]))].append(e.id)
    java_imports: dict[tuple[str, str], set[str]] = defaultdict(set)
    go_packages = {u.path: (str(PurePosixPath(u.path).parent), u.entities[u.path + '::module'].attrs.get('package', ''))
                   for u in units if u.language == 'go'}
    go_types: dict[tuple[tuple[str, str], str], list[str]] = defaultdict(list)
    for e in types.values():
        if e.path in go_packages and e.id.rsplit('/', 1)[0] == e.path + '::module':
            go_types[(go_packages[e.path], e.name)].append(e.id)
    for f in by_relation["EXPORT_SYNTAX"]:
        path = f.subject.removesuffix("::module")
        export_match = re.search(r"export\s+(?:async\s+)?(?:class|interface|function\*?)\s+(\w+)", f.object)
        if export_match:
            exported[(path, export_match[1])] = export_match[1]
        group = re.fullmatch(r"export\s*\{([^}]+)\}\s*;?", f.object)
        if group:
            for item in group[1].split(","):
                names = re.split(r"\s+as\s+", item.strip())
                if names[0]:
                    exported[(path, names[-1])] = names[0]


    rust_common_path: str | None = None

    def rust_module_path(origin: str, module: str) -> str | None:
        """Resolve a Rust module path (``crate::log``, ``model``, ``self::x``) to a file."""
        nonlocal rust_common_path
        segments = [s for s in module.split("::") if s and s != "self"]
        if not segments:
            return None
        directory = str(PurePosixPath(origin).parent)
        base = directory
        if segments[0] == "crate":
            segments = segments[1:]
            if not segments:
                return None
            # The manifest is fixed for this link pass. Re-sorting and splitting
            # every project path for every imported symbol is quadratic on large
            # Rust repositories (including grouped imports).
            if rust_common_path is None:
                rust_common_path = posixpath.commonpath(sorted(paths)) if paths else directory
            common = rust_common_path
            base = common if common not in paths else str(PurePosixPath(common).parent)
        elif segments[0] == "super":
            base = posixpath.dirname(directory)
            segments = segments[1:]
        candidates = []
        for root in (base, directory) if base != directory else (base,):
            stem = posixpath.join(root, *segments) if segments else root
            candidates.extend([stem + ".rs", posixpath.join(stem, "mod.rs")])
        existing = list(dict.fromkeys(p for p in candidates if p in paths))
        return existing[0] if len(existing) == 1 else None

    def module_path(origin: str, module: str, language: str) -> str | None:
        if language == "python":
            from .python_imports import targets
            candidates = targets(origin, module, paths)
        else:
            if not module.startswith("."):
                return None  # Package aliases need a project-specific resolver.
            candidate = posixpath.normpath(posixpath.join(str(PurePosixPath(origin).parent), module))
            candidates = [candidate, *(candidate + ext for ext in (".ts", ".tsx", ".js", ".jsx")),
                          candidate + "/index.ts", candidate + "/index.js"]
        # The same file can appear at two precedences (``models.py`` is both the
        # sibling and the root candidate); dedupe before judging ambiguity.
        existing = list(dict.fromkeys(p for p in candidates if p in paths))
        return existing[0] if len(existing) == 1 else None

    for fact in by_relation["IMPORT_SYNTAX"]:
        origin = fact.subject.removesuffix("::module")
        language = fact.attrs["language"]
        spelling = fact.object
        if language == "java":
            match = re.fullmatch(r"import\s+([\w.]+)\s*;", spelling)
            if match:
                java_imports[(origin, match[1].rsplit(".", 1)[-1])].add(match[1])
        elif language == "python":
            if spelling.startswith("import "):
                for item in spelling.removeprefix("import ").split(","):
                    names = re.split(r"\s+as\s+", item.strip())
                    target = module_path(origin, names[0], language)
                    local = names[-1] if len(names) == 2 else names[0].split('.')[0]
                    import_origins[(origin, local)].add(('module', target or '?' + names[0]))
                    # Dotted unaliased imports bind the leading package, not
                    # its leaf module. Leave that receiver chain unresolved.
                    if target and (len(names) == 2 or "." not in names[0]):
                        module_imports[(origin, names[-1])].add(target)
            match = re.fullmatch(r"from\s+([\w.]+)\s+import\s+(.+)", spelling, re.S)
            if match:
                target = module_path(origin, match[1], language)
                for item in match[2].strip("() \n").split(","):
                    names = re.split(r"\s+as\s+", item.strip())
                    separator = "" if match[1].endswith(".") else "."
                    child = module_path(origin, match[1] + separator + names[0], language)
                    if child and (target, names[0]) not in module_declarations:
                        module_imports[(origin, names[-1])].add(child)
                        import_origins[(origin, names[-1])].add(('module', child))
                    elif names[0] and names[0] != '*':
                        import_origins[(origin, names[-1])].add(
                            ('member', target or '?' + match[1], names[0]))
                if target:
                    for item in match[2].strip("() \n").split(","):
                        names = re.split(r"\s+as\s+", item.strip())
                        if names[0] and names[0] != "*":
                            key, value = (origin, names[-1]), (target, names[0])
                            import_options[key].add(value)
                            if key in imports and imports[key] != value:
                                ambiguous_imports.add(key)
                                imports.pop(key)
                            elif key not in ambiguous_imports:
                                imports[key] = value
        elif language == "rust":
            # ``use crate::log::{self, Level, Log};`` / ``use model::Product;``
            spelling = spelling.strip()
            if not spelling.startswith("use ") or not spelling.endswith(";"):
                continue
            body = spelling[4:-1].strip()
            prefix, _, tail = body.rpartition("::")
            if tail.startswith("{"):
                items = [item.strip() for item in tail.strip("{}").split(",")]
            else:
                items = [tail]
                prefix, _, _ = body.rpartition("::")
            for item in items:
                if not item:
                    continue
                names = re.split(r"\s+as\s+", item)
                original, local = names[0], names[-1]
                if original == "self":
                    original = local = prefix.rsplit("::", 1)[-1]
                module = prefix if original != prefix.rsplit("::", 1)[-1] or item == "self" else prefix
                target = rust_module_path(origin, module or prefix)
                if target:
                    imports[(origin, local)] = (target, original)
        elif language in {"javascript", "typescript"}:
            match = re.search(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", spelling)
            if match:
                target = module_path(origin, match[2], language)
                if target:
                    for item in match[1].split(","):
                        names = re.split(r"\s+as\s+", item.strip().removeprefix("type "))
                        original = exported.get((target, names[0]))
                        if original:
                            imports[(origin, names[-1])] = (target, original)

    # A missing alternative still competes with an acquired import. Selective
    # acquisition must not turn `try local / except external` into certainty.
    ambiguous_imports.update(key for key, origins in import_origins.items() if len(origins) > 1)
    for key in ambiguous_imports:
        imports.pop(key, None)

    bindings_by_scope: dict[tuple[str, str], list[Entity]] = defaultdict(list)
    for e in entities.values():
        if e.kind in {"STORAGE", "PARAMETER", "CALLABLE", "CLASS", "INTERFACE"}:
            bindings_by_scope[(e.id.rsplit("/", 1)[0], e.name)].append(e)

    def resolve(name: str, entity: str) -> str | None:
        if entity not in entities:
            return None
        name = name.strip(": &*?'").removeprefix("mut ")
        # ``&dyn Trait`` / ``impl Trait`` name the same declaration as ``Trait``
        # for member and slot lookup. The concrete call target is still decided
        # separately, so this does not erase dispatch ambiguity.
        name = re.sub(r'^(?:dyn|impl)\s+', '', name).strip()
        origin = entities[entity].path
        scope = entity
        while scope:
            container = entities.get(scope)
            if container is not None and container.attrs.get('expression') and container.name == name:
                return container.id
            if (entities[entity].attrs.get('language') == 'rust' and container is not None
                    and name in container.attrs.get('type_parameters', [])):
                return None
            if entities[entity].kind == "CALL" and not entities[entity].attrs.get("construction"):
                bindings = bindings_by_scope.get((scope, name), [])
                shadowed = any(e.kind in {"STORAGE", "PARAMETER", "CALLABLE"} for e in bindings)
                # A C++ constructor is a CALLABLE named exactly like its class, so
                # ``B(...)`` must still resolve to CLASS:B even though the binding
                # shadows the type name. No other language names a constructor after
                # its own class.
                constructor = any(e.kind == "CALLABLE" and e.attrs.get("constructor") for e in bindings)
                if shadowed and not constructor:
                    return None
            candidate = f"{scope}/CLASS:{name}"
            if candidate in entities:
                return candidate
            candidate = f"{scope}/INTERFACE:{name}"
            if candidate in entities:
                return candidate
            if "/" not in scope:
                break
            scope = scope.rsplit("/", 1)[0]
        imported = imports.get((origin, name))
        if origin in go_packages:
            options = go_types.get((go_packages[origin], name), [])
            return options[0] if len(options) == 1 and go_packages[origin][1] else None
        if origin in java_packages:
            if "." in name:
                options = java_types.get(name, [])
            elif (origin, name) in java_imports:
                imported_names = java_imports[(origin, name)]
                if len(imported_names) != 1:
                    return None
                options = java_types.get(next(iter(imported_names)), [])
            else:
                qualified = ".".join(filter(None, [java_packages[origin], name]))
                options = java_types.get(qualified, [])
            return options[0] if len(options) == 1 else None
        if imported:
            options = class_names.get(imported, [])
        else:
            options = class_names.get((origin, name), [])
        return options[0] if len(options) == 1 else None

    known: dict[str, set[str]] = defaultdict(set)
    declared_types: dict[str, str] = {}
    base_values = {(f.subject, f.attrs.get('name')): f.object for f in by_relation['BASE_VALUE']}
    for f in by_relation["BASE_NAME"]:
        base_binding = base_values.get((f.subject, f.object))
        if base_binding is not None:
            bound = entities[base_binding]
            if base_binding == f.subject or bound.kind in {'PARAMETER', 'CALLABLE'} or bound.kind == 'STORAGE' and bound.attrs.get('declared'):
                continue  # A lexical base value is not a nominal type by spelling.
            if bound.kind in {'CLASS', 'INTERFACE'}:
                graph.add(f.subject, 'SUBTYPE_OF', base_binding, *f.evidence[:1])
                continue
        base_name = f.object
        # Nominal generic bases denote the declaration at their head. Keep this
        # language-gated: Python's Base[T] can be an arbitrary runtime operation.
        if entities[f.subject].attrs.get('language') in {'java', 'csharp', 'cpp', 'typescript'}:
            generic = re.fullmatch(r'([\w.$:]+)\s*<.+>', base_name.strip())
            if generic:
                base_name = generic[1]
        target = resolve(base_name, f.subject)
        if target:
            graph.add(f.subject, "SUBTYPE_OF", target, *f.evidence[:1])
    nominal_heads = {f.subject: f.object for f in by_relation['TYPE_HEAD']}
    opaque_heads = {f.subject for f in by_relation['TYPE_HEAD_STATUS'] if f.object == 'unsupported'}
    for f in by_relation["TYPE_NAME"]:
        spelling = f.object
        declared_entity = entities.get(f.subject)
        unwrapped = False
        if declared_entity is not None and declared_entity.attrs.get('language') == 'rust':
            denoted = rust_denoted_type(spelling)
            unwrapped = denoted != spelling
            spelling = denoted
        if declared_entity is not None:
            declared_entity.attrs["type"] = normalized_type(spelling)
        # ``TYPE_HEAD`` strips a generic argument, which is what resolves
        # ``OnceLock<Service>`` to ``OnceLock``. For a smart pointer the head is the
        # wrapper (``Box``) and the payload is the declaration, so the unwrapped
        # spelling has to win over the head.
        head = spelling if unwrapped else nominal_heads.get(f.subject, spelling)
        if declared_entity is not None and declared_entity.attrs.get('language') == 'go':
            generic = re.fullmatch(r'([\w.]+)\s*\[.+\]', head.strip())
            if generic:
                head = generic[1]
        target = None if f.subject in opaque_heads else resolve(head, f.subject)
        if target:
            known[f.subject].add(target)
            declared_types[f.subject] = target
            graph.add(f.subject, "TYPE", target, *f.evidence[:1])
        element = re.search(r"(?:list|List|Sequence|Collection|Iterable|Array|Vec|vector|IEnumerable|IList|Set)[<\[]\s*([\w]+)", f.object)
        if entities.get(f.subject) is not None and entities[f.subject].attrs.get('language') == 'go':
            element = re.fullmatch(r"\[\]\s*\*?\s*([A-Za-z_]\w*)", f.object.strip())
        if entities.get(f.subject) is not None and entities[f.subject].attrs.get('language') in {'typescript', 'java', 'csharp'}:
            # Exactly one array dimension; T[][] contains arrays, not T values.
            element = element or re.fullmatch(r'\s*([A-Za-z_$][\w.$]*)\s*\[\]\s*', f.object)
        if element:
            target = resolve(element[1], f.subject)
            if target:
                graph.add(f.subject, "ELEMENT_TYPE", target, *f.evidence[:1])
        # A keyed collection has two component types and a walk hands over one or the
        # other: ``for k := range m`` yields the key type, ``for v := range m`` the value
        # type. Publishing both keeps that distinction visible to a query.
        language = entities[f.subject].attrs.get('language') if f.subject in entities else None
        keyed = (re.fullmatch(r"map\s*\[\s*([\w.*]+?)\s*\]\s*([\w.*]+)", f.object.strip()) if language == 'go'
                 else re.fullmatch(r"(?:Map|Dictionary|HashMap|map|dict)\s*<\s*([\w.$]+)\s*,\s*([\w.$]+)\s*>",
                                   f.object.strip()))
        if keyed:
            for relation, spelling in (("KEY_TYPE", keyed[1]), ("VALUE_TYPE", keyed[2])):
                target = resolve(spelling.strip(" *&"), f.subject)
                if target:
                    graph.add(f.subject, relation, target, *f.evidence[:1])
    owners = {f.subject: f.object for f in by_relation["IN_TYPE"]}
    methods: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in by_relation["HAS_METHOD"]:
        methods[(f.subject, entities[f.object].name)].append(f.object)
    bases: dict[str, set[str]] = defaultdict(set)
    for f in graph.facts:
        if f.relation == "SUBTYPE_OF":
            bases[f.subject].add(f.object)

    def ancestors(cls: str) -> set[str]:
        seen: set[str] = set()
        frontier = [cls]
        while frontier:
            current = frontier.pop()
            for base in bases[current]:
                if base not in seen:
                    seen.add(base)
                    frontier.append(base)
        return seen

    for (cls, name), implementations in list(methods.items()):
        if entities[cls].attrs.get('language') == 'cpp':
            continue
        for base in ancestors(cls):
            for impl in implementations:
                for original in methods.get((base, name), []):
                    graph.add(impl, "OVERRIDES", original, f"{entities[impl].path}:{entities[impl].line}")
    from .cpp_methods import virtual_overrides
    virtual_overrides(graph, methods, ancestors, resolve)
    callees = {f.subject: f.object for f in by_relation["CALLEE_NAME"]}
    receivers = {f.subject: f.object for f in by_relation["RECEIVER"]}
    call_owner = {f.object: f.subject for f in by_relation["HAS_CALL"]}
    allocations: dict[str, str] = {}
    for call, name in callees.items():
        if call in receivers:
            continue
        target = resolve(name, call)
        if target:
            allocations[call] = target
            known[call].add(target)
            ev = f"{entities[call].path}:{entities[call].line}"
            graph.add(call, "ALLOCATES_TYPE", target, ev)
            graph.add(call_owner[call], "CREATES", target, ev)
    fields = {(f.subject, entities[f.object].name): f.object for f in by_relation['HAS_FIELD']}
    initializer_names = {f.subject: f.object for f in by_relation['FIELD_NAME']}
    for f in by_relation['HAS_INITIALIZER']:
        target = fields.get((allocations.get(f.subject, ''), initializer_names.get(f.object, '')))
        if target:
            graph.add(f.object, 'INITIALIZES_FIELD', target, *f.evidence[:1], **f.attrs)
    # Assignment edges carry possible types; joins never choose one convenient
    # target when a storage location can hold more than one concrete type.
    changed = False
    for _ in range(16):
        changed = False
        for f in by_relation["ASSIGNED_FROM"]:
            before = len(known[f.subject])
            known[f.subject].update(known[f.object])
            changed |= len(known[f.subject]) != before
        if not changed:
            break
    if changed:
        graph.diagnostics.append("type propagation reached its 16-pass bound")
    for storage, targets in list(known.items()):
        for target in targets:
            graph.add(storage, "TYPE" if len(targets) == 1 and storage not in declared_types else "MAY_TYPE", target)
    for destination, incoming in [(f.subject, f.object) for f in by_relation["ASSIGNED_FROM"]]:
        if destination in entities and incoming in entities and "type" not in entities[destination].attrs:
            entities[destination].attrs["type"] = entities[incoming].attrs.get("type", "unknown")
    for e in list(entities.values()):
        e.attrs.setdefault("type", "unknown")
        if e.kind == "CALLABLE":
            if 'return_type' in e.attrs:
                e.attrs.setdefault('native_return_type', e.attrs['return_type'])
            e.attrs["return_type"] = normalized_type(e.attrs.get("return_type", ""))
    lexical_owners = {f.subject: f.object for f in by_relation["OWNED_BY"]}
    binding_owners = {f.object: f.subject for relation in ('DECLARES', 'HAS_PARAMETER') for f in by_relation[relation]}
    for f in by_relation['READS']:
        binding = entities.get(f.object)
        if binding is None or (binding.kind != 'PARAMETER' and not binding.attrs.get('declared')):
            continue  # Referenced package/global spellings are not local captures.
        owner = binding_owners.get(f.object, '')
        if owner == f.subject or entities.get(owner) is None or entities[owner].kind != 'CALLABLE':
            continue
        scope = lexical_owners.get(f.subject, '')
        while scope and scope != owner:
            scope = lexical_owners.get(scope, '')
        if scope == owner:
            graph.add(f.subject, 'CAPTURES', f.object, *f.evidence[:1], model='lexical-outer-binding')
    lexical_callables: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in entities.values():
        if e.kind == "CALLABLE":
            lexical_callables[(lexical_owners.get(e.id, ""), e.name)].append(e.id)
    for call, name in callees.items():
        if call in receivers or call in allocations:
            continue
        scope = call_owner[call]
        candidates: list[str] = []
        possible_import = False
        while scope:
            if any(e.kind == "PARAMETER" or e.kind == "STORAGE" and (
                    e.attrs.get('language') != 'python' or e.attrs.get('declared'))
                   for e in bindings_by_scope.get((scope, name), [])):
                # Python lowering can materialize a read-only name reference
                # inside a dict/list expression. It is not a local declaration
                # shadowing an explicit import.
                break
            candidates = lexical_callables.get((scope, name), [])
            if candidates:
                break
            scope = lexical_owners.get(scope, scope.rsplit("/", 1)[0] if "/" in scope else "")
        if not candidates and not scope:
            imported = imports.get((entities[call].path, name))
            if imported:
                candidates = lexical_callables.get((imported[0] + "::module", imported[1]), [])
            elif (entities[call].path, name) in ambiguous_imports:
                possible_import = True
                candidates = sorted({candidate
                                     for file, symbol in import_options[(entities[call].path, name)]
                                     for candidate in lexical_callables.get((file + '::module', symbol), [])})
        # A bare member invocation in Java/C#/C++ uses the current instance.
        # Only synthesize this receiver after lexical lookup resolved members:
        # free functions, local callable parameters and static methods have no
        # instance receiver merely because their call appears inside a class.
        caller = entities.get(call_owner[call])
        instance_type = owners.get(call_owner[call])
        if (candidates and caller is not None and instance_type is not None
                and caller.attrs.get('language') in {'java', 'csharp', 'cpp'}
                and not caller.attrs.get('static')
                and all(owners.get(target) in {instance_type, *ancestors(instance_type)}
                        and not entities[target].attrs.get('static')
                        for target in candidates)):
            receiver = instance_type + '/THIS'
            evidence = f"{entities[call].path}:{entities[call].line}"
            graph.add(instance_type, 'INSTANCE_RECEIVER', receiver, evidence,
                      basis='resolved-implicit-instance-member')
            graph.add(call, 'RECEIVER', receiver, evidence,
                      basis='resolved-implicit-instance-member')
        for target in candidates:
            ev = f"{entities[call].path}:{entities[call].line}"
            graph.add(call, "TARGET" if len(candidates) == 1 and not possible_import else "MAY_TARGET", target, ev)
            graph.add(call_owner[call], "CALLS" if len(candidates) == 1 and not possible_import else "MAY_CALLS", target, ev,
                      execution=entities[call].attrs.get('execution', 'unknown'))
    # Audited Java functional slots. These declarations model only the declared
    # invocation contract, not implementation bodies, purity or runtime targets.
    # https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/IntSupplier.html
    # https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/IntUnaryOperator.html
    functional_slots = {
        'java.util.function.IntSupplier': ('getAsInt', 0),
        'java.util.function.IntUnaryOperator': ('applyAsInt', 1),
    }
    type_spellings = {f.subject: f.object for f in by_relation['TYPE_NAME']}
    explicit_arguments: dict[str, list[Fact]] = defaultdict(list)
    for fact in by_relation['ARGUMENT']:
        explicit_arguments[fact.subject].append(fact)

    def external_functional_slot(receiver: str, call: str) -> str | None:
        binding = entities.get(receiver)
        if binding is None or binding.attrs.get('language') != 'java':
            return None
        spelling = type_spellings.get(receiver, '').strip()
        if not spelling or resolve(spelling, receiver) is not None:
            return None  # Source declarations and homonyms take precedence.
        scope = receiver
        while scope:
            container = entities.get(scope)
            if container is not None and spelling in container.attrs.get('type_parameters', []):
                return None
            scope = lexical_owners.get(scope, scope.rsplit('/', 1)[0] if '/' in scope else '')
        imports_for_name = java_imports.get((binding.path, spelling), set())
        qualified = spelling if spelling in functional_slots else (
            next(iter(imports_for_name)) if len(imports_for_name) == 1 else '')
        model = functional_slots.get(qualified)
        if model is None or callees[call] != model[0]:
            return None
        arguments = explicit_arguments.get(call, [])
        if len(arguments) != model[1] or any(a.attrs.get('kind') != 'positional' for a in arguments):
            return None
        model_path = '<model:' + qualified + '>'
        contract = model_path + '::module/INTERFACE:' + qualified.rsplit('.', 1)[-1]
        target = contract + '/CALLABLE:' + model[0]
        if target not in entities:
            common = dict(language='java', external=True, model='java-functional-slots/1')
            entities[contract] = Entity(contract, 'INTERFACE', qualified.rsplit('.',1)[-1],
                                        model_path, 0, 0, common.copy())
            entities[target] = Entity(target, 'CALLABLE', model[0], model_path, 0, 0,
                                      {**common, 'constructor':False, 'static':False, 'functional':True,
                                       'arity':model[1], 'return_type':'int', 'type':'unknown'})
            graph.add(contract, 'HAS_METHOD', target, basis='external-api-contract')
            graph.add(target, 'IN_TYPE', contract, basis='external-api-contract')
            graph.add(target, 'OWNED_BY', contract, basis='external-api-contract')
            for position in range(model[1]):
                parameter = target + '/PARAMETER:operand'
                entities[parameter] = Entity(parameter, 'PARAMETER', 'operand', model_path, 0, 0,
                                              {**common,'receiver':False,'position':position,
                                               'kind':'positional','type':'int'})
                graph.add(target,'HAS_PARAMETER',parameter,position=position,receiver=False,kind='positional')
        graph.add(receiver,'TYPE',contract,basis='external-api-contract')
        return target

    property_accessors = {op.owner for op in graph.operations if op.native_kind == 'method_definition'
                          and op.kind == 'FUNCTION' and {'get', 'set'} & set(op.attrs.get('tokens', []))}
    for call, receiver in receivers.items():
        binding = entities.get(receiver)
        imported_module = (module_imports.get((binding.path, binding.name))
                           if binding is not None and binding.kind == 'STORAGE'
                           and not binding.attrs.get('declared') else None)
        if imported_module and binding is not None:
            candidates = sorted({target for module in imported_module
                                 for target in lexical_callables.get((module + '::module', callees[call]), [])})
            certain = len(candidates) == 1 and (binding.path, binding.name) not in ambiguous_imports
            for target in candidates:
                ev = f"{entities[call].path}:{entities[call].line}"
                graph.add(call, 'TARGET' if certain else 'MAY_TARGET', target, ev,
                          basis='explicit-module-import')
                graph.add(call_owner[call], 'CALLS' if certain else 'MAY_CALLS', target, ev,
                          basis='explicit-module-import', execution=entities[call].attrs.get('execution', 'unknown'))
            continue
        if receiver in types and entities[receiver].attrs.get('language') in {'java', 'csharp', 'javascript', 'typescript', 'python'}:
            name = callees[call]
            # A class-valued receiver selects its own static declarations. Do not
            # reinterpret that class as an instance or guess inherited lookup.
            shadowed = (entities[receiver].attrs.get('language') in {'javascript', 'typescript'}
                        and ((receiver, name) in fields
                             or any(m in property_accessors for m in methods.get((receiver, name), []))))
            static_targets = [] if shadowed else [m for m in methods.get((receiver, name), [])
                                           if entities[m].attrs.get('static') and m not in property_accessors]
            if entities[receiver].attrs.get('language') == 'python':
                # Only the direct built-in descriptor spelling is modeled.
                # Additional decorators or field assignments can replace it.
                static_targets = [m for m in static_targets
                                  if entities[m].attrs.get('decorators') in (['@classmethod'], ['@staticmethod'])
                                  and (receiver, name) not in fields
                                  and not any(f.object == m for f in by_relation['ASSIGNMENT_TARGET'])]
            for target in static_targets:
                ev = f"{entities[call].path}:{entities[call].line}"
                graph.add(call, 'TARGET' if len(static_targets) == 1 else 'MAY_TARGET', target, ev,
                          basis='direct-class-static')
                graph.add(call_owner[call], 'CALLS' if len(static_targets) == 1 else 'MAY_CALLS', target, ev,
                          basis='direct-class-static', execution=entities[call].attrs.get('execution', 'unknown'))
            continue
        modeled_slot = external_functional_slot(receiver, call)
        if modeled_slot is not None:
            graph.add(call, 'DECLARED_TARGET', modeled_slot,
                      f'{entities[call].path}:{entities[call].line}',
                      basis='external-api-contract', model='java-functional-slots/1')
        possible = {receiver.removesuffix("/THIS")} if receiver.endswith("/THIS") else known[receiver]
        name = callees[call]
        declared = declared_types.get(receiver)
        if declared is not None:
            slots = set(methods.get((declared, name), []))
            if not slots:
                for base in ancestors(declared):
                    slots.update(methods.get((base, name), []))
            if len(slots) == 1:
                graph.add(call, 'DECLARED_TARGET', next(iter(slots)),
                          f'{entities[call].path}:{entities[call].line}', basis='nominal-annotation')
        method_targets: set[str] = set()
        for cls in possible:
            direct = methods.get((cls, name), [])
            method_targets.update(direct)
            if not direct:
                for base in ancestors(cls):
                    method_targets.update(methods.get((base, name), []))
        for target in method_targets:
            ev = f"{entities[call].path}:{entities[call].line}"
            graph.add(call, "TARGET" if len(method_targets) == 1 else "MAY_TARGET", target, ev)
            graph.add(call_owner[call], "CALLS" if len(method_targets) == 1 else "MAY_CALLS", target, ev,
                      execution=entities[call].attrs.get('execution', 'unknown'))
        for cls in possible:
            graph.add(call_owner[call], "DELEGATES_TYPE", cls, f"{entities[call].path}:{entities[call].line}", name=name,
                      execution=entities[call].attrs.get('execution', 'unknown'))
    resolved_call_ids = {f.subject for f in graph.facts if f.relation == "TARGET"}
    ambiguous_call_ids = {f.subject for f in graph.facts if f.relation == "MAY_TARGET"}
    for e in entities.values():
        if e.kind == "CALL":
            e.attrs["resolution"] = ("ambiguous" if e.id in ambiguous_call_ids else
                                      "resolved" if e.id in resolved_call_ids else "unresolved")
    assigned = defaultdict(set)
    for f in by_relation["ASSIGNED_FROM"]:
        assigned[f.subject].add(f.object)
    from .return_flow import sequential_returns
    precise_returns = sequential_returns(graph)
    for f in by_relation["RETURNS"]:
        if f.object in entities and entities[f.object].kind == "STORAGE":
            graph.add(f.subject, "RETURNS_STORAGE", f.object, *f.evidence[:1], execution=f.attrs.get('execution', 'unknown'))
        precise = precise_returns.get((f.subject, f.object))
        possible_values = set(precise) if precise is not None else {f.object}
        frontier = [] if precise is not None else [f.object]
        while frontier and len(possible_values) <= 256:
            current = frontier.pop()
            for value in assigned[current]:
                if value not in possible_values:
                    possible_values.add(value)
                    frontier.append(value)
        for value in sorted(possible_values):
            if value in allocations:
                attrs = {'modality': 'may', 'basis': 'flow'} if precise is not None and len(precise) > 1 else {}
                attrs['execution'] = f.attrs.get('execution', 'unknown')
                graph.add(f.subject, "RETURNS_NEW", allocations[value], *f.evidence[:1], **attrs)
                if f.subject in owners and owners[f.subject] == allocations[value]:
                    graph.add(f.subject, "RETURNS_NEW_SELF", owners[f.subject], *f.evidence[:1], **attrs)
        if f.object in callees:
            graph.add(f.subject, "RETURNS_CALL", f.object, *f.evidence[:1], execution=f.attrs.get('execution', 'unknown'))
    resolved_calls = {f.subject: f.object for f in graph.facts if f.relation == "TARGET"}
    params = defaultdict(list)
    returns = defaultdict(list)
    for f in by_relation["HAS_PARAMETER"]:
        if not f.attrs.get("receiver"):
            params[f.subject].append(f)
    for f in by_relation["RETURNS"]:
        returns[f.subject].append(f.object)
    arguments_by_call = defaultdict(list)
    for argument in by_relation["ARGUMENT"]:
        arguments_by_call[argument.subject].append(argument)
    for call, target in resolved_calls.items():
        for arg in arguments_by_call[call]:
            for param in params[target]:
                exact = (arg.attrs["kind"] == "positional" and param.attrs["position"] == arg.attrs["position"]
                         or arg.attrs["kind"] == "named" and entities[param.object].name == arg.attrs["name"])
                if exact:
                    graph.add(arg.object, "BINDS_TO", param.object, *arg.evidence[:1])
                    graph.add(arg.object, "FLOWS_TO", param.object, *arg.evidence[:1])
                elif arg.attrs["kind"].startswith("spread"):
                    graph.add(arg.object, "MAY_BIND_TO", param.object, *arg.evidence[:1])
        for value in returns[target]:
            graph.add(value, "FLOWS_TO", call)
    from .field_initialization import field_initial_values
    field_initial_values(graph, declared_types)
    # Enrich selector metadata through facts; lexical names remain available for
    # explicit user predicates, but catalogue roles do not depend on them.
    for f in by_relation["HAS_PARAMETER"]:
        e = entities[f.object]
        e.attrs.update(pos=f.attrs["position"], parameter_kind=f.attrs["kind"])
    from .base_dispatch import resolve as resolve_base_dispatch
    resolve_base_dispatch(graph)
    from .functional_interfaces import annotate as annotate_functional_interfaces
    annotate_functional_interfaces(graph)
    for e in entities.values():
        if e.kind == 'CALL' and not graph.diagnostics:
            e.attrs['explicit_arguments'] = len(arguments_by_call[e.id])
        graph.add(e.id, "ENTITY", e.kind, f"{e.path}:{e.line}", **{**e.attrs, "name": e.name})
    for op in graph.operations:
        graph.add(op.id, "OPERATION", op.kind, f"{graph.entities[op.owner].path}:{op.line}",
                  kind=op.kind, native_kind=op.native_kind, owner=op.owner, role=op.role,
                  start_byte=op.start, end_byte=op.end, **op.attrs)
        graph.add(op.owner, "HAS_OPERATION", op.id, execution=op.attrs.get('execution', 'unknown'))
    if not graph.diagnostics:
        graph.capabilities.add("resolved_types")
    from .effects import concurrency_effects
    from .syntax_graph import syntax_contexts
    from .java_optional import optional_facts
    from .type_refs import annotation_types
    from .control_flow import structured_control
    from .collection_snapshots import collection_snapshots
    from .member_access import member_access
    from .nominal_roots import nominal_roots
    from .call_bindings import call_bindings
    from .field_transfers import field_transfers
    from .member_transfers import member_transfers
    from .binding_writes import binding_writes
    from .collection_lifecycle import collection_lifecycle
    annotation_types(graph)
    structured_control(graph)
    syntax_contexts(graph)
    from .normal_completion import normal_completion
    normal_completion(graph)
    collection_snapshots(graph)
    collection_lifecycle(graph)
    nominal_roots(graph)
    member_access(graph)
    from .structural_contracts import structural_contracts
    structural_contracts(graph)
    from .events import csharp_events
    csharp_events(graph)
    call_bindings(graph)
    field_transfers(graph)
    member_transfers(graph)
    binding_writes(graph)
    optional_facts(graph)
    concurrency_effects(graph)
    from .construction import resolved_allocations
    resolved_allocations(graph)
    from .write_inventory import explicit_write_inventory
    explicit_write_inventory(graph)
    from .value_contracts import value_contracts
    value_contracts(graph)
    return graph
