"""Tree-sitter lowering with explicit, tested grammar families.

The operation layer retains every named syntax node and its field/ordering.
Semantic facts are a separate, conservative projection: an unknown construct
is preserved as NATIVE, never silently interpreted as a familiar construct.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from tree_sitter import Node, Parser

from .model import Entity, IR, Operation
from .construction import callable_access, constructor_inventory
from .cpp_methods import function_parts, method_info, parameter_head, parameter_info, prototype_origin

LANGUAGES = {".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
             ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
             ".java": "java", ".cs": "csharp", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
             ".go": "go", ".rs": "rust"}
TYPES = {"class", "abstract_class_declaration", "class_definition", "class_declaration", "interface_declaration", "class_specifier",
         "struct_specifier", "struct_item", "trait_item", "type_spec", "record_declaration",
         "enum_specifier", "enum_item", "enum_declaration"}
# Declarations whose body names a closed set of constants rather than fields.
# Python reaches the same shape through ``class_definition`` and Go through a
# module-level ``const`` block, so only these need the constants read off the
# declaration itself.
ENUM_TYPES = {"enum_specifier", "enum_item", "enum_declaration"}
ENUM_CONSTANTS = {"enumerator", "enum_variant", "enum_constant", "enum_member_declaration",
                  "property_identifier"}
# Grammars that spell type parameters as a declaration group. Python and JavaScript have
# no such syntax, so their declarations skip the ancestor walk entirely.
TYPE_PARAMETER_LANGUAGES = {"typescript", "java", "csharp", "cpp", "go", "rust"}
FUNCTIONS = {"abstract_method_signature", "function_definition", "function_declaration", "method_definition", "method_declaration",
             "constructor_declaration", "function_item", "function_signature_item", "method_signature",
             # Go declares an interface's required operations as ``method_elem``.
             "method_elem",
             # Rust closures are ``closure_expression``; a closure is a callable like
             # the ``lambda`` and ``arrow_function`` forms of the other languages.
             "closure_expression",
             "generator_function_declaration", "generator_function", "arrow_function", "lambda",
             "local_function_statement", "func_literal", "function_expression", "lambda_expression"}
MEMBERS = {"attribute", "member_expression", "field_access", "member_access_expression",
           "selector_expression", "field_expression"}
INDEXES = {"subscript", "subscript_expression", "element_access_expression", "index_expression", "array_access"}
CALLS = {"call", "call_expression", "method_invocation", "invocation_expression", "new_expression",
         "object_creation_expression", "struct_expression", "composite_literal",
         # A constructor delegating to another constructor is an invocation, and the
         # grammars name it as one. Without these a Java/C# constructor body could
         # contain a call the graph never records, which would make HAS_CALL
         # completeness unsound rather than merely incomplete.
         "explicit_constructor_invocation", "constructor_initializer"}
ASSIGNMENTS = {"assignment", "assignment_expression", "assignment_statement", "short_var_declaration",
               "variable_declarator", "init_declarator", "let_declaration", "public_field_definition", "field_definition", "field_declaration",
               "var_declaration", "const_declaration", "static_item", "const_item"}
# Dictionary access spelled as a method call. ``put``/``set``/``insert`` are only
# treated as a write when the call supplies at least two arguments, so a property
# setter (``obj.set(x)``) is not read as an indexed write.
MAP_READS = {"get", "Get", "fetch", "Fetch", "lookup", "Lookup", "getOrDefault", "GetValueOrDefault"}
MAP_WRITES = {"put", "Put", "set", "Set", "add", "Add", "insert", "Insert", "store", "Store",
              "emplace", "Emplace", "try_emplace", "insert_or_assign", "AddOrUpdate", "GetOrAdd",
              "setdefault", "setDefault"}
# A return statement, whatever the grammar calls it.
RETURN_TYPES = {"return_statement", "return_expression"}
# Declarations that bind a name outside any callable. Go spells both name and
# initializer on a ``var_spec``/``const_spec`` child rather than on the
# declaration itself, so the declaration only carries an assignment once that
# spec is resolved; Rust puts both fields on the item directly.
FILE_DECLARATIONS = {"var_declaration", "const_declaration", "static_item", "const_item"}
SPEC_DECLARATIONS = {"var_declaration": "var_spec", "const_declaration": "const_spec"}
LOOPS = {"for_statement", "for_in_statement", "enhanced_for_statement", "for_each_statement",
         "foreach_statement", "for_expression", "for_range_loop", "while_statement", "while_expression", "loop_expression", "do_statement"}
BRANCHES = {"if_statement", "if_expression", "conditional_expression", "ternary_expression"}
WRAPPERS = {"expression_list", "parenthesized_expression", "type", "type_annotation", "argument",
            "expression_statement", "reference_expression", "pointer_expression",
            # C++ wraps an if/while condition in a ``condition_clause``; it is a
            # pure wrapper, so unwrapping it exposes the tested expression.
            "condition_clause"}
OPERATOR_NODES = {"binary_expression", "binary_operator", "comparison_operator", "boolean_operator",
                  "unary_expression", "unary_operator", "not_operator", "update_expression",
                  "prefix_unary_expression", "postfix_unary_expression", "augmented_assignment",
                  "augmented_assignment_expression"}

# Lexical blocks that scope a local declaration. JS/TS ``var``
# (``variable_declaration``) is function-scoped and is deliberately absent, so
# two ``var`` declarations of one name remain a single binding.
BLOCK_SCOPES = {"block", "statement_block", "compound_statement"}
BLOCK_DECLARATIONS = {
    "javascript": {"lexical_declaration"},
    "typescript": {"lexical_declaration"},
    "java": {"local_variable_declaration"},
    "csharp": {"variable_declaration"},
}


def field(node: Node | None, *names: str) -> Node | None:
    if node is not None:
        for name in names:
            child = node.child_by_field_name(name)
            if child is not None:
                return child
    return None


def children(node: Node | None) -> list[Node]:
    return node.named_children if node is not None else []


def loop_binding(loop: Node | None) -> Node | None:
    """The variable a loop binds to each element.

    Field spellings differ per grammar: Python/JS use ``left``, C++ range-for uses
    ``declarator`` and wraps it in a (possibly reference) declarator.
    """
    node = field(loop, "left", "name", "pattern", "declarator")
    while node is not None and node.type in {"reference_declarator", "pointer_declarator",
                                             "init_declarator", "variable_declarator"}:
        node = next(iter(node.named_children), None)
    return node


def descendants(node: Node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.named_children))


def _member_storage(entity_id: str) -> bool:
    """Is this entity a field or a module-level binding rather than a local?

    Locals and parameters are owned by a callable, so their id carries the owning
    ``/CALLABLE:`` segment; a field or a module-level storage does not. Used to
    keep ``map.get(k)`` on a local from being read as a pool lookup.
    """
    return "/CALLABLE:" not in entity_id


def parser_for(language: str, path: str) -> Parser:
    if language not in set(LANGUAGES.values()):
        raise ValueError(f"structural frontend unavailable for {language}")
    module = importlib.import_module(f"ken.parsers.{language}")
    name = "_PARSER_TSX" if path.endswith(".tsx") else "_PARSER_TS"
    existing = getattr(module, name if language == "typescript" else "_PARSER")
    # Reuse Ken's grammar, with a separate mutable parser per lowering call.
    return Parser(existing.language)


class Lowerer:
    def __init__(self, source: bytes, language: str, path: str):
        self.source = source
        self.ir = IR(path, language)
        self.tree = parser_for(language, path).parse(source)
        self.module = f"{path}::module"
        self.ir.entities[self.module] = Entity(self.module, "MODULE", path, path, 1,
                                              self.tree.root_node.end_point[0] + 1)
        # The module entity is built here rather than through ``entity()``, so it
        # needs its own kind fact: every other entity gets one, and a query must
        # be able to state that a subject is a module.
        self.ir.add(self.module, "IS", "MODULE", f"{path}:1", basis="module-root")
        self.node_entities: dict[int, str] = {}
        self.owner: dict[int, str] = {}
        self.class_owner: dict[int, str] = {}
        self.methods: dict[str, list[str]] = {}
        self.names: dict[tuple[str, str], str] = {}
        self.block_locals: dict[tuple[str, int, str], str] = {}
        self.enum_constants: dict[str, set[str]] = {}
        self.receivers: dict[str, str] = {}
        self.type_nodes: dict[str, Node] = {}
        self.call_nodes: dict[str, Node] = {}
        self.context_decorators: set[str] = set()
        for item in descendants(self.tree.root_node):
            if item.type == "import_from_statement":
                match = re.fullmatch(r"from\s+contextlib\s+import\s+(.+)", self.text(item), re.S)
                if match:
                    for imported in match[1].strip("() \n").split(","):
                        parts = re.split(r"\s+as\s+", imported.strip())
                        if parts[0] in {"contextmanager", "asynccontextmanager"}:
                            self.context_decorators.add(parts[-1])
            elif item.type == "import_statement":
                match = re.fullmatch(r"import\s+contextlib(?:\s+as\s+(\w+))?", self.text(item))
                if match:
                    prefix = match[1] or "contextlib"
                    self.context_decorators.update(prefix + "." + name for name in ("contextmanager", "asynccontextmanager"))
        # ``export { a }`` / ``export default a`` expose a name declared elsewhere
        # in the module, so collect them before walking declarations.
        self.exported_names: set[str] = set()
        for item in descendants(self.tree.root_node):
            if item.type == "export_statement":
                self.exported_names |= self.export_clause_names(item)
        # A local definition/assignment can shadow an imported decorator. Do
        # not apply a standard-library model to that spelling in such a file.
        shadowed = set()
        for item in descendants(self.tree.root_node):
            if item.type in FUNCTIONS | TYPES:
                shadowed.add(self.name(item))
            elif item.type in ASSIGNMENTS:
                left = field(item, "left", "name", "pattern")
                if left is not None and left.type == "identifier":
                    shadowed.add(self.text(left))
        self.context_decorators = {name for name in self.context_decorators if name.split(".")[0] not in shadowed}
        self.pending_bases: list[tuple[str, str, str]] = []
        self.base_references: list[tuple[str, Node, str]] = []
        self.pending_types: list[tuple[str, str, str]] = []
        self.cpp_field_initializers: dict[int, list[tuple[str, str, Node]]] = {}
        self.cpp_method_declarations: set[int] = set()
        self.ir.capabilities.update({"syntax", "declarations", "calls", "local_storage", "control",
                                     "parameters", "imports", "generators"})

    def text(self, node: Node | None) -> str:
        return self.source[node.start_byte:node.end_byte].decode("utf-8", "replace") if node else ""

    def evidence(self, node: Node) -> str:
        return f"{self.ir.path}:{node.start_point[0] + 1}"

    def annotate_type(self, subject: str, annotation: Node, evidence: str) -> None:
        self.pending_types.append((subject, self.text(annotation), evidence))
        if self.ir.language != 'rust':
            return
        head = annotation
        for _ in range(32):
            if head.type not in {'reference_type', 'pointer_type', 'generic_type'}:
                break
            nested = field(head, 'type')
            if nested is None:
                return
            head = nested
        if head.type == 'type_identifier':
            self.ir.add(subject, 'TYPE_HEAD', self.text(head), evidence, basis='annotation-syntax')

    def cpp_field_declaration(self, node: Node, scope: str) -> None:
        """Bind each class-field declarator to its slot, retaining the written type."""
        annotation = field(node, 'type')
        declared_count = 0
        unsupported = False
        for i, declarator in enumerate(node.children):
            if node.field_name_for_child(i) != 'declarator':
                continue
            current: Node | None = declarator
            indirections = 0
            complex_type = False
            for _ in range(32):
                if current is None or current.type in {'identifier', 'field_identifier'}:
                    break
                if current.type == 'function_declarator':
                    nested = self.declarator(current)
                    # Ordinary methods (including pointer-returning methods) are not fields.
                    if (nested is None or nested.type != 'parenthesized_declarator'
                            or not any(n.type in {'pointer_declarator', 'reference_declarator'} for n in descendants(nested))):
                        current = None
                        break
                    complex_type = True
                elif current.type == 'array_declarator':
                    complex_type = True
                elif current.type in {'pointer_declarator', 'reference_declarator'}:
                    indirections += 1
                elif current.type != 'parenthesized_declarator':
                    unsupported = True
                    current = None
                    break
                nested = self.declarator(current)
                if nested is None and current.type == 'parenthesized_declarator':
                    nested = next((c for c in current.named_children if c.type != 'comment'), None)
                current = nested
            if current is None:
                continue
            if current.type not in {'identifier', 'field_identifier'} or annotation is None:
                unsupported = True
                continue
            target = self.storage(self.text(current), scope, current)
            static = any(c.type == 'storage_class_specifier' and self.text(c) == 'static'
                         for c in node.named_children)
            self.ir.entities[target].attrs.update(declared=True, static=static)
            for fact in self.ir.facts:
                if fact.subject == scope and fact.object == target and fact.relation in {'DECLARES', 'HAS_FIELD'}:
                    fact.attrs['static'] = static
            abstract = (self.source[declarator.start_byte:current.start_byte]
                        + self.source[current.end_byte:declarator.end_byte]).decode('utf-8', 'replace')
            base_parts = [self.text(c) for c in node.named_children if c == annotation or c.type == 'type_qualifier']
            native = ' '.join([*base_parts, abstract]).strip()
            self.pending_types.append((target, native, self.evidence(declarator)))
            nominal = annotation.type == 'type_identifier' and not complex_type and indirections <= 1
            self.ir.add(target, 'TYPE_HEAD_STATUS', 'supported' if nominal else 'unsupported',
                        self.evidence(declarator), basis='cpp-declarator-syntax')
            if nominal:
                self.ir.add(target, 'TYPE_HEAD', self.text(annotation), self.evidence(declarator),
                            basis='cpp-declarator-syntax')
            declared_count += 1
            # The grammar places each default after its declarator, before the next comma.
            for j in range(i + 1, len(node.children)):
                child = node.children[j]
                if child.type in {',', ';'} or node.field_name_for_child(j) == 'declarator':
                    break
                if node.field_name_for_child(j) != 'default_value':
                    continue
                operation = f'{self.ir.path}::op:{declarator.start_byte}:{declarator.end_byte}:{declarator.type}'
                self.cpp_field_initializers.setdefault(node.id, []).append((operation, target, child))
                break
        operation = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{node.type}'
        self.ir.add(operation, 'CPP_FIELD_DECL_STATUS', 'unsupported' if unsupported else 'supported' if declared_count else 'not-storage',
                    self.evidence(node), basis='declarator-syntax', fields=declared_count)

    def bound_type_parameters(self, node: Node) -> list[str]:
        names: set[str] = set()
        current: Node | None = node
        for _ in range(64):
            if current is None:
                break
            # Rust, TypeScript, Java and Go spell the group ``type_parameters``; C#
            # spells it ``type_parameter_list``; C++ wraps the declaration in a
            # ``template_declaration`` whose group is the ``parameters`` field. Only
            # the ``type_parameter_declaration`` node type is read from that last one,
            # so a function's ordinary parameter list — which uses the same field name
            # — is never mistaken for a type-parameter group.
            groups = [field(current, 'type_parameters'), field(current, 'type_parameter_list')]
            if current.type == 'template_declaration':
                groups.append(field(current, 'parameters'))
            if all(group is None for group in groups):
                # C# leaves ``type_parameter_list`` unfielded, so it has to be found by
                # node type among the declaration's own children.
                groups.append(next((child for child in current.named_children
                                    if child.type == 'type_parameter_list'), None))
            for group in groups:
                for parameter in children(group):
                    if parameter.type in {'type_parameter', 'const_parameter', 'type_parameter_declaration'}:
                        name = field(parameter, 'name')
                        if name is None:
                            name = next((child for child in parameter.named_children
                                         if child.type in {'type_identifier', 'identifier'}), None)
                        if name is not None:
                            names.add(self.text(name))
            current = current.parent
        return sorted(names)

    def type_parameter_reference(self, spelling: str, bound: list[str]) -> str | None:
        """The bound type parameter a declared type refers to, if it is one.

        ``Visitor &``, ``&V``, ``const T *`` and ``&mut T`` all name the parameter
        through reference, pointer or qualifier decoration; the parameter itself is the
        identity a query wants to join on, so the decoration is stripped before the
        comparison. Anything else returns ``None`` and keeps its own name.
        """
        if not spelling or not bound:
            return None
        stripped = re.sub(r'\b(?:const|mut|ref|volatile)\b', ' ', spelling)
        for decoration in ('&', '*', '&&'):
            stripped = stripped.replace(decoration, ' ')
        candidate = ' '.join(stripped.split())
        return candidate if candidate in bound else None

    def entity(self, kind: str, name: str, scope: str, node: Node, **attrs: Any) -> str:
        key = f"{scope}/{kind}:{name}@{node.start_byte}" if kind in {"CALL", "PARAMETER", "CALLABLE"} else f"{scope}/{kind}:{name}"
        if kind == 'CLASS' and node.type == 'class':
            key += f'@{node.start_byte}'
        if kind == "CALL":
            # f(x)(y) has two calls starting at the same byte; the end offset
            # distinguishes the producer from invocation of its result.
            key += f":{node.end_byte}"
        if key not in self.ir.entities:
            if self.ir.language in TYPE_PARAMETER_LANGUAGES and kind in {'CLASS', 'INTERFACE', 'CALLABLE'}:
                parameters = self.bound_type_parameters(node)
                attrs['type_parameters'] = parameters
                # A declaration binds its parameters by name. The fact is what lets a
                # query join a field's ``TYPE_NAME`` to the parameter it stands for:
                # an attribute list is not reachable from KenQL.
                for parameter in parameters:
                    self.ir.add(key, 'BINDS_TYPE_PARAMETER', parameter, self.evidence(node))
            self.ir.entities[key] = Entity(key, kind, name, self.ir.path,
                                           node.start_point[0] + 1, node.end_point[0] + 1, {**attrs, "native_kind": node.type, "language": self.ir.language, "start_byte": node.start_byte, "end_byte": node.end_byte})
            self.ir.add(key, "IS", kind, self.evidence(node), **attrs)
        return key

    def declarator(self, node: Node | None) -> Node | None:
        declared = field(node, 'declarator')
        if declared is not None:
            return declared
        if node is not None and node.type == 'reference_declarator':
            return next(iter(node.named_children), None)
        return None

    def name(self, node: Node) -> str:
        named = field(node, "name")
        if named is None:
            declarator = self.declarator(node)
            while self.declarator(declarator) is not None:
                declarator = self.declarator(declarator)
            named = declarator
        return self.text(named) or f"anonymous@{node.start_byte}"

    def parameters(self, node: Node) -> Node | None:
        current: Node | None = node
        # C++ pointer/reference return declarators wrap the function declarator.
        # Follow only the declared function's chain, never nested parameter types.
        for _ in range(32):
            if current is None:
                break
            parameters = field(current, "parameters")
            if parameters is not None:
                return parameters
            current = self.declarator(current)
        return None

    def declare(self, node: Node, scope: str, cls: str = "") -> None:
        kind = node.type
        cpp_origin = prototype_origin(node) if self.ir.language == 'cpp' and cls and scope == cls else None
        if cpp_origin is not None:
            self.cpp_method_declarations.add(cpp_origin.id)
        if kind in TYPES and not (kind == "enum_specifier" and field(node, "body") is None):
            # Go type aliases are not silently promoted to classes. A body-less
            # C++ ``enum_specifier`` is an elaborated *reference* (``enum State``
            # in a declaration), not a definition, so it declares no type.
            type_node = field(node, "type")
            if kind == "type_spec" and type_node is not None and type_node.type not in {"struct_type", "interface_type"}:
                pass
            else:
                name = self.name(node)
                type_kind = "INTERFACE" if "interface" in kind or kind == "trait_item" or type_node is not None and type_node.type == "interface_type" else "CLASS"
                expression = kind == 'class'
                enclosing_scope = scope
                declared = self.entity(type_kind, name, scope, node, **({'expression': True} if expression else {}))
                self.ir.add(scope, "DECLARES", declared, self.evidence(node), kind="type-expression" if expression else "type", name=name)
                self.mark_export(scope, declared, name, node)
                if expression:
                    if field(node, 'name') is not None:
                        self.names[(declared, name)] = declared
                    oid = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}'
                    self.ir.add(oid, 'CLASS_EXPRESSION', declared, self.evidence(node), basis='class-expression-syntax')
                else:
                    self.names[(scope, name)] = declared
                self.type_nodes[declared] = node
                self.node_entities[node.id] = declared
                if kind in ENUM_TYPES:
                    self.enum_constants[declared] = self.enum_constant_names(node)
                if self.ir.language == "rust":
                    attribute = node.prev_named_sibling
                    while attribute is not None and attribute.type in {"attribute_item", "line_comment", "block_comment"}:
                        match = re.fullmatch(r"#\[\s*derive\s*\(([^()]*)\)\s*\]", self.text(attribute))
                        if match:
                            for derived in match[1].split(","):
                                spelling = derived.strip()
                                if re.fullmatch(r"\w+(?:::\w+)*", spelling):
                                    self.ir.add(declared, "DERIVE_NAME", spelling, self.evidence(attribute))
                        attribute = attribute.prev_named_sibling
                cls, scope = declared, declared
                for item in node.named_children:
                    if item.type in {"argument_list", "class_heritage", "superclass", "super_interfaces",
                                     "base_list", "base_class_clause"}:
                        roots = item.named_children
                        if item.type in {"class_heritage", "super_interfaces"}:
                            roots = [leaf for part in roots for leaf in (part.named_children if part.type in {"extends_clause", "implements_clause", "type_list"} else [part])]
                        for base in roots:
                            if base.type == "access_specifier":
                                continue
                            self.pending_bases.append((declared, self.text(base), self.evidence(base)))
                            if (type_kind == 'CLASS' and self.ir.language in {'python', 'javascript', 'typescript'}
                                    and (base.parent is None or base.parent.type != 'implements_clause')
                                    and base.type in {'identifier', 'type_identifier'}):
                                reference_scope = declared if expression and self.text(base) == name else enclosing_scope
                                self.base_references.append((declared, base, reference_scope))
        elif kind in {"field_declaration", "declaration"} and self.ir.language == "cpp" and scope == cls:
            self.cpp_field_declaration(node, scope)
        elif kind in {"field_declaration", "declaration"} and self.ir.language == "cpp":
            # C++ class fields are visible in inline methods even when their
            # declarations follow the method bodies.
            for i, child in enumerate(node.children):
                if node.field_name_for_child(i) != "declarator":
                    continue
                if any(n.type == "function_declarator" for n in descendants(child)):
                    continue
                declared_node = child
                while True:
                    nested_declarator = field(declared_node, "declarator")
                    if nested_declarator is None:
                        break
                    declared_node = nested_declarator
                if declared_node.type in {"field_identifier", "identifier"}:
                    self.storage(self.text(declared_node), scope, declared_node)
        elif kind in FILE_DECLARATIONS and scope == self.module:
            # A file-scope declaration binds a module-scope name. Creating the
            # binding while declaring, rather than on the first read that cannot
            # resolve it, keeps the identity of the storage independent of
            # whether the file reads or declares the name first — otherwise the
            # read invents a callable-local slot with the same spelling.
            spec_type = SPEC_DECLARATIONS.get(kind)
            specs = ([c for c in node.named_children if c.type == spec_type]
                     if spec_type is not None else [node])
            for spec in specs:
                for declared_name in self.declared_names(spec):
                    if declared_name.type in {"identifier", "field_identifier"}:
                        self.storage(self.text(declared_name), scope, declared_name)
        elif kind == "impl_item":
            target_node = field(node, "type")
            # Type arguments specialize a nominal declaration; they are not
            # part of its declaration name. Qualified paths remain unresolved
            # here rather than binding to an unrelated local basename.
            if target_node is not None and target_node.type == "generic_type":
                target_node = field(target_node, "type")
            target = self.text(target_node)
            cls = self.names.get((scope, target), "") if target_node is not None and target_node.type == "type_identifier" else ""
            if cls:
                scope = cls
                trait = self.text(field(node, "trait"))
                if trait:
                    self.pending_bases.append((cls, trait, self.evidence(node)))
        elif kind in FUNCTIONS or cpp_origin is not None:
            # Go receiver methods live outside the struct declaration.
            receiver = field(node, "receiver")
            if receiver:
                parameter = next(iter(receiver.named_children), None)
                # A generic receiver spells its type arguments too (``*Abstraction[I]``),
                # and the declaration is named without them. Keeping the arguments would
                # leave the method owned by the module instead of by its type.
                target = re.sub(r'\[[^\]]*\]\s*$', '', self.text(field(parameter, "type"))).lstrip("*").strip()
                cls = self.names.get((self.module, target), "")
                if cls:
                    scope = cls
            name = self.name(node)
            cpp_parts = function_parts(node) if self.ir.language == 'cpp' else None
            if cpp_parts is not None:
                name = self.text(cpp_parts[1])
            declaration = self.text(node).split("{", 1)[0].split("\n", 1)[0]
            static = bool(re.search(r"\bstatic\b", declaration))
            decorators = node.parent if node.parent and node.parent.type == "decorated_definition" else None
            decor = [self.text(d) for d in children(decorators) if d.type == "decorator"]
            classmethod = any(d == "@classmethod" for d in decor)
            static = static or classmethod or "@staticmethod" in decor
            # A nested callable retains lexical ownership, never the enclosing class's methods.
            direct_method = bool(cls and scope == cls and kind not in {"lambda_expression", "lambda", "arrow_function", "func_literal", "function_expression"})
            cpp_attrs = method_info(self.source, node, cpp_origin if cpp_origin is not None else node) if self.ir.language == 'cpp' and direct_method else {}
            static = cpp_attrs.get('static', static)
            function = self.entity("CALLABLE", name, scope, node, static=static,
                                   constructor=name in {"__init__", "__new__", "constructor"} or kind == "constructor_declaration" or
                                   bool(self.ir.language == "cpp" and direct_method and name == self.ir.entities[cls].name),
                                   async_=(any(self.text(c) == "async" for c in node.children) if kind in {"arrow_function", "lambda_expression"} else bool(re.search(r"\basync\b", declaration))), decorators=decor,
                                   context_manager=any(d.removeprefix("@") in self.context_decorators for d in decor))
            if direct_method:
                self.ir.entities[function].attrs.update(callable_access(self.ir.language, node, self.ir.entities[cls].kind))
            annotation = self.text(field(node, "return_type", "returns", "result", "type"))
            self.ir.entities[function].attrs["return_type"] = annotation.strip(": ") or "unknown"
            self.ir.entities[function].attrs["native_return_type"] = annotation.strip(": ")
            if self.ir.language == 'cpp' and direct_method:
                self.ir.entities[function].attrs.update(cpp_attrs)
                self.ir.entities[function].attrs['return_type'] = cpp_attrs.get('native_return_type') or 'unknown'
            # ``-> Builder<Ready>`` is the declaring type applied to another argument:
            # that is how a typestate step records the state it moved to, and the
            # argument is unrecoverable from the bare type name.
            return_spelling = self.ir.entities[function].attrs.get('native_return_type') or annotation
            applied = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*<\s*(.+?)\s*>\s*', return_spelling or '')
            if applied is not None and cls and self.ir.entities[cls].name == applied[1]:
                self.ir.add(function, 'RETURN_TYPE_ARGUMENT', applied[2], self.evidence(node))
            self.ir.entities[function].attrs["generator"] = "generator" in kind
            self.node_entities[node.id] = function
            self.names[(scope, name)] = function
            self.ir.add(scope, "DECLARES", function, self.evidence(node), kind="callable", name=name, static=static)
            self.mark_export(scope, function, name, node)
            if direct_method:
                self.ir.add(cls, "HAS_METHOD", function, self.evidence(node), name=name, static=static)
                self.methods.setdefault(cls, []).append(function)
                self.ir.add(function, "IN_TYPE", cls, self.evidence(node))
            self.ir.add(function, "OWNED_BY", scope, self.evidence(node))
            parameters = self.parameters(node)
            keyword_only = False
            positional_only = parameters is not None and any(c.type == "positional_separator" for c in parameters.named_children)
            parameter_nodes = children(parameters)
            if self.ir.language == 'cpp' and len(parameter_nodes) == 1 and self.text(parameter_nodes[0]) == 'void':
                parameter_nodes = []
            if parameters is not None and parameters.type in {"identifier", "implicit_parameter"}:
                parameter_nodes = [parameters]
            single_parameter = field(node, "parameter")
            if parameters is None and single_parameter is not None:
                parameter_nodes = [single_parameter]
            # A parameter whose declared type is one of its callable's own type
            # parameters stands for that parameter: ``Visitor &`` in C++ and ``&V`` in
            # Rust both name it through reference decoration.
            bound_parameters = self.bound_type_parameters(node) if self.ir.language in TYPE_PARAMETER_LANGUAGES else []
            for position, param in enumerate(parameter_nodes):
                if param.type == "positional_separator":
                    positional_only = False
                    continue
                if param.type == "keyword_separator":
                    keyword_only = True
                    continue
                spelling = self.text(param)
                pname_node = field(param, "name", "pattern", "declarator")
                if pname_node is None:
                    pname_node = next((d for d in descendants(param) if d.type in {"identifier", "self"}), param)
                pname = self.text(pname_node).lstrip("*&.")
                cpp_parameter_type = ''
                cpp_parameter_name = None
                cpp_reference_kind = ''
                if self.ir.language == 'cpp':
                    cpp_parameter_name, cpp_parameter_type = parameter_info(self.source, param)
                    pname = self.text(cpp_parameter_name) if cpp_parameter_name is not None else f'anonymous@{param.start_byte}'
                    # ``X(const X&)`` and ``X(X&&)`` differ only by the reference
                    # kind, and C++ binds them to different protocols: one copies,
                    # the other moves. The declarator spelling is the only place
                    # that distinction exists.
                    declarator = field(param, 'declarator')
                    if declarator is not None and declarator.type == 'reference_declarator':
                        tokens = [self.text(c) for c in declarator.children if not c.is_named]
                        cpp_reference_kind = 'rvalue' if '&&' in tokens else 'lvalue'
                variadic_keyword = spelling.startswith("**")
                variadic = spelling.startswith("*") or "..." in spelling or any(d.type in {"rest_pattern", "list_splat_pattern"} for d in descendants(param))
                parameter_kind = ("variadic_keyword" if variadic_keyword else "variadic_positional" if variadic
                                  else "keyword_only" if keyword_only else "positional_only" if positional_only else "positional")
                is_receiver = direct_method and position == 0 and (pname in {"self", "cls"} or param.type == "self_parameter")
                pid = self.entity("PARAMETER", pname, function, param, kind_=parameter_kind, position=position, receiver=is_receiver)
                if cpp_reference_kind:
                    self.ir.entities[pid].attrs["reference_kind"] = cpp_reference_kind
                if bound_parameters:
                    referenced = self.type_parameter_reference(
                        cpp_parameter_type or self.text(field(param, 'type')), bound_parameters)
                    if referenced:
                        self.ir.add(pid, 'TYPE_PARAMETER', referenced, self.evidence(param))
                if self.ir.language != 'cpp' or cpp_parameter_name is not None:
                    self.names[(function, pname)] = pid
                default_node = field(param, 'value', 'default_value')
                if default_node is None and self.ir.language == 'csharp':
                    equal = next((i for i, child in enumerate(param.children) if child.type == '='), None)
                    if equal is not None:
                        default_node = next((child for child in param.children[equal + 1:]
                                             if child.is_named and child.type != 'comment'), None)
                self.ir.add(function, "HAS_PARAMETER", pid, self.evidence(param), kind=parameter_kind, position=position - (1 if direct_method and self.ir.language == "python" and not is_receiver and self.receivers.get(function) else 0), receiver=is_receiver,
                            default=self.text(default_node))
                annotation_node = field(param, "type")
                annotation = self.text(annotation_node)
                if self.ir.language == 'cpp' and cpp_parameter_type:
                    self.pending_types.append((pid, cpp_parameter_type, self.evidence(param)))
                    cpp_head = parameter_head(cpp_parameter_type)
                    self.ir.add(pid, 'TYPE_HEAD_STATUS', 'supported' if cpp_head else 'unsupported',
                                self.evidence(param), basis='cpp-parameter-declarator-syntax')
                    if cpp_head:
                        self.ir.add(pid, 'TYPE_HEAD', cpp_head, self.evidence(param),
                                    basis='cpp-parameter-declarator-syntax')
                elif annotation_node is not None:
                    self.annotate_type(pid, annotation_node, self.evidence(param))
                property_modifiers = {self.text(c) for c in param.children
                                      if c.type in {'accessibility_modifier', 'readonly'}}
                if (self.ir.language == 'typescript' and direct_method and name == 'constructor'
                        and field(node, 'body') is not None and pname_node.type == 'identifier'
                        and property_modifiers & {'public', 'private', 'protected', 'readonly'}):
                    slot = self.storage(pname, cls, param)
                    self.ir.entities[slot].attrs.update(declared=True, parameter_property=True,
                                                       readonly='readonly' in property_modifiers)
                    self.ir.add(pid, 'PARAMETER_INITIALIZES_FIELD', slot, self.evidence(param),
                                basis='typescript-parameter-property')
                    self.ir.add(slot, 'ASSIGNED_FROM', pid, self.evidence(param),
                                basis='typescript-parameter-property')
                    self.ir.add(function, 'WRITES', slot, self.evidence(param), implicit=True)
                    if annotation_node is not None:
                        self.annotate_type(slot, annotation_node, self.evidence(param))
                if is_receiver:
                    self.receivers[function] = pname
                if variadic:
                    keyword_only = True
            if direct_method and self.ir.language != "python":
                self.receivers[function] = "self" if self.ir.language == "rust" else "this"
            if receiver:
                parameter = next(iter(receiver.named_children), None)
                self.receivers[function] = self.text(field(parameter, "name"))
            for decorator in decor:
                self.ir.add(function, "DECORATED_BY", decorator, self.evidence(node))
            scope = function
        self.owner[node.id] = scope
        self.class_owner[node.id] = cls
        for child in sorted(node.named_children, key=lambda c: 0 if c.type in TYPES | {"type_declaration"} else 1):
            self.declare(child, scope, cls)

    def resolve_name(self, name: str, scope: str) -> str | None:
        while scope:
            if (scope, name) in self.names:
                return self.names[(scope, name)]
            if scope == self.module:
                break
            scope = scope.rsplit("/", 1)[0]
        return self.names.get((self.module, name))

    def block_scope(self, node: Node) -> Node | None:
        """Innermost lexical block enclosing ``node``, stopping at the callable."""
        current = node.parent
        while current is not None and current.type not in FUNCTIONS:
            if current.type in BLOCK_SCOPES:
                return current
            current = current.parent
        return None

    def is_body_block(self, block: Node) -> bool:
        """True for a callable body, which is not a nested lexical scope."""
        return block.parent is not None and block.parent.type in FUNCTIONS

    def block_local(self, name: str, scope: str, node: Node) -> str | None:
        """Innermost block-scoped declaration of ``name`` visible at ``node``.

        Walks outward from the read, so a name declared in a nearer block wins
        over the callable-level binding and an inner block's binding stops
        applying once the read leaves it.
        """
        current = node.parent
        while current is not None and current.type not in FUNCTIONS:
            if current.type in BLOCK_SCOPES:
                known = self.block_locals.get((scope, current.id, name))
                if known is not None:
                    return known
            current = current.parent
        return None

    def block_storage(self, name: str, scope: str, block: Node, node: Node) -> str:
        """Declare a block-local binding that shadows an enclosing one.

        :meth:`storage` is keyed by ``(scope, name)``, which cannot represent
        two declarations of one spelling in different lexical blocks: they would
        share a single write set. Allocating a separate entity keeps the
        bindings apart so provenance never mixes the inner and the outer value.
        """
        key = (scope, block.id, name)
        known = self.block_locals.get(key)
        if known is not None:
            return known
        sid = f"{scope}/STORAGE:{name}@{block.start_byte}"
        if sid not in self.ir.entities:
            self.ir.entities[sid] = Entity(
                sid, "STORAGE", name, self.ir.path, node.start_point[0] + 1, node.end_point[0] + 1,
                {"static": False, "native_kind": node.type, "language": self.ir.language,
                 "start_byte": node.start_byte, "end_byte": node.end_byte, "block_scope": block.id})
            self.ir.add(sid, "IS", "STORAGE", self.evidence(node), static=False)
        self.block_locals[key] = sid
        self.ir.add(scope, "DECLARES", sid, self.evidence(node), kind="storage", name=name, static=False)
        return sid

    def unwrap(self, node: Node) -> Node:
        while node.type in WRAPPERS and len(node.named_children) == 1:
            node = node.named_children[0]
        return node

    def enum_constant_names(self, node: Node) -> set[str]:
        """Names a nominal enum declaration introduces as constants.

        The constant is a *declaration*, not a field: a reference to it has one
        identity for the whole graph even though the spelling recurs. Only the
        body's own children are read, so a TS ``property_identifier`` elsewhere
        in the declaration is never mistaken for a constant.
        """
        names: set[str] = set()
        for item in children(field(node, "body")):
            if item.type not in ENUM_CONSTANTS:
                continue
            named = field(item, "name")
            spelling = self.text(named) if named is not None else self.text(item)
            if re.fullmatch(r"[A-Za-z_$][\w$]*", spelling):
                names.add(spelling)
        return names

    def declared_names(self, node: Node) -> list[Node]:
        """Every name the node declares, in declaration order.

        A repeated field (Go's ``var a, b = 1, 2``) yields each name, so a caller
        can refuse the shape instead of silently keeping only the first.
        """
        return [child for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "name"]

    def declaration_parts(self, node: Node) -> tuple[Node | None, Node | None]:
        """The declared name and the initializer of a declaration node.

        Go carries both on a single ``var_spec``/``const_spec`` child, so the
        declaration node itself has no ``name``/``value`` field to read. Shapes
        whose single operand list is paired with several targets are left
        unresolved: one declaration node cannot carry two independent assignment
        occurrences without inventing which value reached which name.
        """
        source = node
        spec_type = SPEC_DECLARATIONS.get(node.type)
        if spec_type is not None:
            specs = [c for c in node.named_children if c.type == spec_type]
            if len(specs) != 1:
                return None, None
            source = specs[0]
        names = self.declared_names(source)
        if len(names) > 1:
            return None, None
        left = names[0] if names else field(source, "left", "pattern", "declarator", "property")
        return left, field(source, "right", "value")

    def member_parts(self, node: Node) -> tuple[Node | None, str]:
        obj = field(node, "object", "expression", "operand", "argument", "value")
        member = field(node, "attribute", "property", "field", "name")
        # C# `this` is an unnamed token.
        if obj is None and node.children and node.children[0].type == "this":
            obj = node.children[0]
        return obj, self.text(member)

    def value(self, node: Node | None, scope: str, cls: str) -> str:
        if node is None:
            return f"{scope}/UNKNOWN"
        node = self.unwrap(node)
        if node.type in {'unary_expression', 'unary_operator'}:
            # ``&slot`` and ``*pointer`` denote the storage itself: an argument that
            # addresses a slot is evidence about that slot. Go passes the destination
            # this way (``json.Unmarshal(payload, &e.state)``), where an assignment is
            # what the other languages use.
            operator = ' '.join(self.text(c) for c in node.children if not c.is_named)
            operands = [c for c in node.named_children if 'comment' not in c.type]
            if operator in {'&', '*'} and len(operands) == 1:
                return self.value(operands[0], scope, cls)
        if self.ir.language == 'typescript' and node.type in {'as_expression', 'type_assertion', 'non_null_expression', 'satisfies_expression'}:
            parts = [c for c in node.named_children if 'comment' not in c.type]
            if parts:
                inner = parts[-1] if node.type == 'type_assertion' else parts[0]
                value = self.value(inner, scope, cls)
                oid = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{node.type}'
                self.ir.add(oid, 'TYPE_ASSERTION_VALUE', value, self.evidence(node), basis='typescript-erased-assertion')
                return value
        if node.type in FUNCTIONS and node.id in self.node_entities:
            return self.node_entities[node.id]
        if node.type == 'class' and node.id in self.node_entities:
            return self.node_entities[node.id]
        spelling = self.text(node)
        receiver = self.receivers.get(scope, "")
        # ``super.m()`` / ``base.m()`` call the inherited member **on this object**,
        # so the receiver denotes the same instance as ``this``; without that the
        # receiver of an inherited call dangles and a query cannot see that the
        # object is the one being acted on. Rust and C++ have no such keyword
        # (``super::`` there is a module path, and ``Base::m()`` names the base), so
        # the spelling is admitted per language.
        base_receivers = ({'super'} if self.ir.language in {'java', 'python', 'javascript', 'typescript'}
                          else {'base'} if self.ir.language == 'csharp' else set())
        if spelling and spelling in {receiver, "this", "self"} | base_receivers and cls:
            value = f"{cls}/THIS"
            method = self.ir.entities.get(scope)
            if method is not None and method.kind == 'CALLABLE' and not method.attrs.get('static'):
                self.ir.add(cls, 'INSTANCE_RECEIVER', value, self.evidence(node), basis='instance-relative')
            return value
        if node.type in {"none", "null", "null_literal", "nil", "nil_literal"} or spelling in {"None", "null", "nil", "nullptr"}:
            return "NULL"
        if node.type in CALLS or self.go_indexed_call(node, scope, cls) is not None:
            return self.entity("CALL", str(node.start_byte), scope, node)
        if node.type in MEMBERS:
            obj, member = self.member_parts(node)
            objname = self.text(obj)
            if cls and (objname in {receiver, "this", "self", self.ir.entities[cls].name}):
                return self.storage(member, cls, node, static=objname == self.ir.entities[cls].name or objname == "cls")
            base = self.value(obj, scope, cls)
            result = self.entity("MEMBER", member, base, node)
            self.ir.add(result, "MEMBER_OF", base, self.evidence(node))
            return result
        if node.type in {"qualified_identifier", "scoped_identifier"}:
            # C++/Rust spell a named constant ``Enum::Constant``. The entity is
            # keyed by the declaring type and the constant, not by the offset, so
            # every reference shares one identity. Without that a "distinct
            # written values" check would be satisfied by writing the same state
            # twice, which is the opposite of a transition.
            qualifier_node = field(node, "scope", "path")
            constant_node = field(node, "name")
            if qualifier_node is not None and constant_node is not None:
                qualifier = self.resolve_name(self.text(qualifier_node), scope)
                if qualifier is not None and self.text(constant_node) in self.enum_constants.get(qualifier, ()):
                    result = self.entity("MEMBER", self.text(constant_node), qualifier, node)
                    self.ir.add(result, "MEMBER_OF", qualifier, self.evidence(node))
                    return result
        if node.type in {"identifier", "field_identifier", "property_identifier", "private_property_identifier", "type_identifier", "self"}:
            # A declaration in a nearer lexical block wins over the callable-level
            # binding of the same spelling.
            shadowing = self.block_local(spelling, scope, node)
            if shadowing is not None:
                return shadowing
            return self.resolve_name(spelling, scope) or self.storage(spelling, scope, node)
        if node.type in {"list", "list_expression", "array", "array_expression", "array_creation_expression", "dictionary", "object", "map_literal"}:
            collection_kind = ('map' if node.type in {'dictionary','map_literal'} else 'record' if node.type == 'object'
                               else 'list' if self.ir.language == 'python' else 'array')
            collection = self.entity("COLLECTION", str(node.start_byte), scope, node, collection_kind=collection_kind)
            if (node.type in {'list', 'array', 'dictionary', 'object'}
                    and not any(c.type == ',' for c in node.children)
                    and not any('comment' not in c.type for c in node.named_children)):
                self.ir.add(collection, 'EMPTY_COLLECTION', collection_kind, self.evidence(node), basis='literal')
            return collection
        primitive = {"integer": "int", "integer_literal": "int", "int_literal": "int", "float": "float", "float_literal": "float", "string": "str", "string_literal": "str", "true": "bool", "false": "bool", "boolean": "bool", "number": "number"}.get(node.type, "unknown")
        if node.type in {'character_literal','char_literal'}:
            primitive = 'char'
        return self.entity("VALUE", str(node.start_byte), scope, node, native_kind=node.type, type=primitive)

    def storage(self, name: str, scope: str, node: Node, static: bool = False) -> str:
        known = self.names.get((scope, name))
        if known:
            return known
        sid = self.entity("STORAGE", name, scope, node, static=static)
        self.names[(scope, name)] = sid
        self.ir.add(scope, "DECLARES", sid, self.evidence(node), kind="storage", name=name, static=static)
        if scope in self.type_nodes:
            self.ir.add(scope, "HAS_FIELD", sid, self.evidence(node), name=name, static=static)
        return sid

    def export_clause_names(self, node: Node) -> set[str]:
        """Local names exposed by ``export { ... }`` or ``export default x``.

        Those forms carry no marker on the declaration itself, so the names are
        collected before declarations are walked.
        """
        text = " ".join(self.text(node).split())
        names: set[str] = set()
        group = re.fullmatch(r'export\s*\{([^}]*)\}\s*;?', text)
        if group:
            for item in group[1].split(','):
                local = re.split(r'\s+as\s+', item.strip())[0].strip()
                if re.fullmatch(r'[A-Za-z_$][\w$]*', local):
                    names.add(local)
        default = re.fullmatch(r'export\s+default\s+([A-Za-z_$][\w$]*)\s*;?', text)
        if default:
            names.add(default[1])
        return names

    def export_basis(self, name: str, node: Node) -> str | None:
        """Why a module-level declaration is a public entry, or ``None``.

        Visibility follows the language's own rule, never a project convention:
        an explicit ``export`` (JS/TS), a ``pub`` modifier (Rust), or the
        language's public-naming rule (upper-case in Go, no leading underscore
        in Python). ``__all__`` is not interpreted: a module-level public name
        stays importable whether or not it is re-listed there.
        """
        language = self.ir.language
        if language in {'javascript', 'typescript'}:
            if node.parent is not None and node.parent.type == 'export_statement':
                return 'explicit-export'
            return 'export-clause' if name in self.exported_names else None
        if language == 'rust':
            published = any(child.type == 'visibility_modifier' and self.text(child).strip().startswith('pub')
                            for child in node.children)
            return 'visibility-modifier' if published else None
        if language == 'go':
            return 'public-name' if name[:1].isupper() else None
        if language == 'python':
            return 'public-name' if name and not name.startswith('_') else None
        return None

    def mark_export(self, scope: str, entity: str, name: str, node: Node) -> None:
        """Record ``module EXPORT symbol`` for a public module-level entry.

        The relation links the module to the symbol it exposes, so a query can
        require an entry point without depending on a class or a field.
        """
        if scope != self.module:
            return
        basis = self.export_basis(name, node)
        if basis is None:
            return
        self.ir.add(scope, "EXPORT", entity, self.evidence(node), name=name, basis=basis)

    def go_indexed_call(self, node: Node, scope: str, cls: str) -> tuple[str, str] | None:
        if self.ir.language != "go" or node.type != "type_conversion_expression" or not cls:
            return None
        generic = field(node, "type")
        qualified = field(generic, "type")
        if generic is None or generic.type != "generic_type" or qualified is None or qualified.type != "qualified_type":
            return None
        if self.text(field(qualified, "package")) != self.receivers.get(scope):
            return None
        container = self.names.get((cls, self.text(field(qualified, "name"))))
        arguments = field(generic, "type_arguments")
        if not container or arguments is None or len(arguments.named_children) != 1:
            return None
        annotation = next((name for subject, name, _ in self.pending_types if subject == container), "")
        if not re.match(r"map\[[^\]]+\]func\s*\(", annotation):
            return None
        key = self.resolve_name(self.text(arguments.named_children[0]), scope)
        return (container, key) if key is not None else None

    def lower(self) -> IR:
        # Declare types first so Go receivers and Rust impl blocks resolve even
        # when their declarations occur later in the file.
        self.declare(self.tree.root_node, self.module)
        for node in descendants(self.tree.root_node):
            self.operation(node)
        for node in descendants(self.tree.root_node):
            self.semantics(node)
        for subject, name, evidence in self.pending_bases:
            self.ir.add(subject, "BASE_NAME", name, evidence)
        for subject, base, reference_scope in self.base_references:
            binding = self.resolve_name(self.text(base), reference_scope)
            if binding is not None:
                self.ir.add(subject, 'BASE_VALUE', binding, self.evidence(base),
                            name=self.text(base), basis='lexical-base-syntax')
        for subject, name, evidence in self.pending_types:
            if subject in self.ir.entities:
                self.ir.entities[subject].attrs["native_type"] = name.strip(": ")
            self.ir.add(subject, "TYPE_NAME", name.strip(": "), evidence)
        if self.tree.root_node.has_error:
            self.ir.diagnostics.append("parse errors: semantic absence is unknown")
            self.ir.capabilities.discard("declarations")
        if self.ir.language == 'cpp':
            from .cpp_initializers import initializer_values
            initializer_values(self.ir)
        constructor_inventory(self.ir, self.type_nodes)
        from .effects import syntax_effects
        syntax_effects(self)
        return self.ir

    def argument_value(self, argument: Node, scope: str, cls: str) -> str:
        """The value an argument supplies, past the grammar's argument wrapper.

        Only argument wrappers expose their expression via ``value``; a Python
        subscript also has that field, but it is the container, not the expression
        passed to the callee.
        """
        valnode = field(argument, "value", "expression") if argument.type in {"keyword_argument", "argument"} else None
        if valnode is None and argument.type == "argument" and argument.named_children:
            valnode = argument.named_children[-1]
        return self.value(valnode or argument, scope, cls)

    def operation(self, node: Node) -> None:
        native = node.type
        owner = self.owner[node.id]
        if native in TYPES:
            kind = "TYPE"
        elif native == 'field_initializer' and self.ir.language == 'cpp':
            kind = 'INITIALIZE'
        elif native in FUNCTIONS or (node.id in self.node_entities and self.ir.entities[self.node_entities[node.id]].kind == 'CALLABLE'):
            kind = "FUNCTION"
        elif native in CALLS:
            kind = "CALL"
        elif native in ASSIGNMENTS:
            kind = "DECLARATION" if node.id in self.cpp_method_declarations else "ASSIGN"
            bare_declarator = (
                native == 'variable_declarator' and self.ir.language in {'javascript', 'typescript', 'java', 'csharp'}
                or native == 'let_declaration' and self.ir.language == 'rust'
                or native in FILE_DECLARATIONS
                or native == 'assignment' and self.ir.language == 'python' and node.child_by_field_name('type') is not None
            )
            if (bare_declarator and self.declaration_parts(node)[1] is None
                    and not any(c.type == '=' for c in node.children)):
                kind = 'DECLARATION'
        elif native in MEMBERS:
            kind = "MEMBER"
        elif native in LOOPS:
            kind = "LOOP"
        elif native in BRANCHES:
            kind = "BRANCH"
        else:
            kind = next((label for token, label in [("yield", "YIELD"), ("await", "AWAIT"), ("return", "RETURN"),
                        ("import", "IMPORT"), ("export", "EXPORT"), ("use_declaration", "IMPORT"),
                        ("type_parameter", "TYPE_PARAMETER"), ("match", "MATCH"), ("switch", "MATCH"),
                        ("with_statement", "RESOURCE_SCOPE"), ("using_statement", "RESOURCE_SCOPE"),
                        ("try", "TRY"), ("throw", "THROW"), ("raise", "THROW"),
                        ("decorator", "DECORATOR"), ("splat", "SPREAD"), ("spread", "SPREAD"),
                        ("rest_pattern", "VARIADIC")] if token in native), "NATIVE")
        parent = node.parent
        role = ""
        if parent:
            for i, child in enumerate(parent.children):
                if child.id == node.id:
                    role = parent.field_name_for_child(i) or ""
                    break
        attrs: dict[str, Any] = {}
        if not node.named_children:
            attrs["text"] = self.text(node)
        # Operators and modifiers can be unnamed tree-sitter nodes.
        attrs["tokens"] = [self.text(c) for c in node.children if not c.is_named]
        # An async loop advances through the async protocol (``async for``,
        # ``for await``, ``await foreach``). The distinction is not recoverable
        # from the iteration facts, which a plain loop over the same source also
        # carries, so it has to be recorded on the loop itself.
        if native in LOOPS and any(token in {"async", "await"} for token in attrs["tokens"]):
            attrs["async"] = True
        operator_tokens = [t for t in attrs['tokens'] if t in {
            '+', '-', '*', '/', '//', '%', '**', '=', ':=', '+=', '-=', '*=', '/=', '//=', '%=', '**=',
            '<', '>', '<=', '>=', '==', '!=', '===', '!==', '<=>', '&&', '||', '!', 'and', 'or', 'not',
            '&', '|', '^', '~', '<<', '>>', '>>>', '&=', '|=', '^=', '<<=', '>>=', '>>>=',
            '++', '--', 'in', 'not in', 'is', 'is not', '??', '??=', '&&=', '||='}]
        operator_node = (native in OPERATOR_NODES or native in ASSIGNMENTS) and node.id not in self.cpp_method_declarations
        if operator_node and operator_tokens:
            if native in ASSIGNMENTS or native in {'augmented_assignment', 'augmented_assignment_expression'}:
                kind = 'ASSIGN'
            elif any(t in {'++', '--'} for t in operator_tokens):
                kind = 'UPDATE'
            elif any(t in {'<', '>', '<=', '>=', '==', '!=', '===', '!==', '<=>', 'in', 'not in', 'is', 'is not'} for t in operator_tokens):
                kind = 'COMPARE'
            elif native in {'unary_expression', 'unary_operator', 'not_operator', 'prefix_unary_expression', 'postfix_unary_expression'}:
                kind = 'UNARY'
            else:
                kind = 'BINARY'
        if kind == "YIELD":
            attrs["delegated"] = "from" in attrs["tokens"] or "*" in attrs["tokens"]
        oid = f"{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{native}"
        parent_id = f"{self.ir.path}::op:{parent.start_byte}:{parent.end_byte}:{parent.type}" if parent else None
        self.ir.operations.append(Operation(oid, kind, native, parent_id, role, node.start_byte, node.end_byte,
                                            node.start_point[0] + 1, owner, attrs))
        if operator_node and operator_tokens:
            for position, token in enumerate(operator_tokens):
                self.ir.add(oid, 'OPERATOR', token, self.evidence(node), position=position,
                            short_circuit=token in {'and', 'or', '&&', '||', '??', '&&=', '||=', '??='})
            if native in ASSIGNMENTS:
                operand_nodes = [field(node, 'left', 'name', 'pattern', 'declarator'), field(node, 'right', 'value')]
                if operand_nodes[1] is None and self.ir.language == 'csharp':
                    equal = next((i for i,c in enumerate(node.children) if c.type == '='), None)
                    if equal is not None:
                        operand_nodes[1] = next((c for c in node.children[equal+1:] if c.is_named and c.type != 'comment'), None)
            else:
                operand_nodes = [c for c in node.named_children if c.type not in {'comment', 'line_comment', 'block_comment'}
                                 and c != field(node, 'operator')]
            for position, operand in enumerate(operand_nodes):
                if operand is not None:
                    operand_id = f'{self.ir.path}::op:{operand.start_byte}:{operand.end_byte}:{operand.type}'
                    self.ir.add(oid, 'OPERAND', operand_id, self.evidence(node), position=position)
        if kind in {"YIELD", "AWAIT", "IMPORT", "EXPORT", "MATCH", "RESOURCE_SCOPE", "TYPE_PARAMETER"}:
            self.ir.add(owner, f"HAS_{kind}", oid, self.evidence(node), native_kind=native)
        if node.is_error or node.is_missing:
            self.ir.diagnostics.append(f"{self.evidence(node)}: {native}")

    def enclosing(self, node: Node, kinds: set[str]) -> Node | None:
        parent = node.parent
        while parent and parent.type not in FUNCTIONS:
            if parent.type in kinds:
                return parent
            parent = parent.parent
        return None

    def semantics(self, node: Node) -> None:
        scope, cls = self.owner[node.id], self.class_owner[node.id]
        kind, ev = node.type, self.evidence(node)
        if kind == 'field_initializer' and self.ir.language == 'cpp':
            from .cpp_initializers import record_initializer
            record_initializer(self, node, scope, cls)
        if kind == "package_clause" and self.ir.language == "go" and node.named_children:
            self.ir.entities[self.module].attrs["package"] = self.text(node.named_children[0])
        callable_scope = self.ir.entities.get(scope) is not None and self.ir.entities[scope].kind == "CALLABLE"
        if kind in LOOPS:
            iteration_node = node
            if self.ir.language == 'go':
                iteration_node = next((c for c in node.named_children if c.type == 'range_clause'), node)
            foreach = kind in {'for_in_statement','enhanced_for_statement','for_each_statement','foreach_statement','for_expression','for_range_loop'} or self.ir.language == 'python' and kind == 'for_statement' or iteration_node.type == 'range_clause'
            if foreach:
                left, right = field(iteration_node,'left','name','pattern','declarator'), field(iteration_node,'right','value','iterable')
                body = field(node,'body')
                if left is not None and right is not None and body is not None:
                    oid = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}'
                    self.ir.add(oid,'ITERATION_SOURCE',self.value(right,scope,cls),ev)
                    self.ir.add(oid,'ITERATION_BODY',f'{self.ir.path}::op:{body.start_byte}:{body.end_byte}:{body.type}',ev)
                    iteration_bindings = left.named_children if self.ir.language == 'go' and left.type == 'expression_list' else [left]
                    for position, binding in enumerate(iteration_bindings):
                        while self.ir.language == 'cpp':
                            nested_declaration = field(binding,'declarator')
                            if nested_declaration is None and binding.type == 'reference_declarator':
                                candidates = [c for c in binding.named_children if 'comment' not in c.type]
                                nested_declaration = candidates[0] if len(candidates) == 1 else None
                            if nested_declaration is None:
                                break
                            binding = nested_declaration
                        if binding.type not in {'identifier','field_identifier'} or self.text(binding) == '_' and self.ir.language in {'go','rust'}:
                            continue
                        key_iteration = self.ir.language in {'javascript','typescript'} and any(c.type == 'in' for c in node.children)
                        role = 'first' if self.ir.language == 'go' and position == 0 else 'key' if key_iteration else 'value'
                        self.ir.add(oid,'ITERATION_BINDING',self.value(binding,scope,cls),ev,position=position,role=role)
        if kind in {"if_statement", "if_expression"}:
            condition = field(node, "condition")
            if condition is not None:
                condition = self.unwrap(condition)
                tested = condition
                positive = True
                for _ in range(32):
                    operands = [c for c in tested.named_children if 'comment' not in c.type]
                    operator = ' '.join(self.text(c) for c in tested.children if not c.is_named)
                    if (tested.type not in {'not_operator', 'unary_expression', 'prefix_unary_expression'}
                            or operator not in {'not', '!'} or len(operands) != 1):
                        break
                    positive = not positive
                    tested = self.unwrap(operands[0])
                if tested.type in CALLS | MEMBERS | {'identifier'}:
                    oid = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}'
                    self.ir.add(oid, 'TRUTH_TEST', self.value(tested, scope, cls), ev,
                                when='true' if positive else 'false', basis='condition-syntax')
                    for arm, name in [('BRANCH_TRUE', 'consequence'), ('BRANCH_FALSE', 'alternative')]:
                        body = field(node, name)
                        if body is not None:
                            self.ir.add(oid, arm, f'{self.ir.path}::op:{body.start_byte}:{body.end_byte}:{body.type}', ev)
                elif (tested.type in {'comparison_operator', 'binary_expression'} and len(operands) == 2
                        and operator in {'==', '!=', '===', '!=='}
                        and not any(self.value(side, scope, cls) == 'NULL' for side in operands)):
                    # ``kind == Num`` discriminates ``kind``: the branch tests a slot
                    # against a case. Publishing the slot is what lets a query ask
                    # "this branch dispatches on that tag field" instead of only "this
                    # callable contains a branch". Either side may be the slot, so both
                    # are offered and only those that denote a slot are published. No
                    # polarity is claimed: which arm a comparison selects is not the
                    # truthiness of the value.
                    oid = f'{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}'
                    for side in operands:
                        tested_value = self.value(side, scope, cls)
                        tested_entity = self.ir.entities.get(tested_value)
                        if tested_entity is not None and tested_entity.kind in {'STORAGE', 'MEMBER'}:
                            self.ir.add(oid, 'TRUTH_TEST', tested_value, ev, basis='comparison-syntax')
                    for arm, name in [('BRANCH_TRUE', 'consequence'), ('BRANCH_FALSE', 'alternative')]:
                        body = field(node, name)
                        if body is not None:
                            self.ir.add(oid, arm, f'{self.ir.path}::op:{body.start_byte}:{body.end_byte}:{body.type}', ev)
                operands = [c for c in tested.named_children if 'comment' not in c.type]
                operator = " ".join(self.text(c) for c in tested.children if not c.is_named)
                # A neutral null comparison; logical negation changes its polarity.
                if tested.type in {"comparison_operator", "binary_expression"} and len(operands) == 2 and operator in {"is", "is not", "==", "!=", "===", "!=="}:
                    null_left, null_right = (self.value(c, scope, cls) for c in operands)
                    if (null_left == "NULL") != (null_right == "NULL"):
                        oid = f"{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}"
                        self.ir.add(oid, "NULL_TEST", null_right if null_left == "NULL" else null_left, ev,
                                    when="true" if (operator in {"is", "==", "==="}) == positive else "false",
                                    operator=operator, negated=not positive)
                        for arm, names in [("BRANCH_TRUE", ("consequence",)), ("BRANCH_FALSE", ("alternative",))]:
                            body = field(node, *names)
                            if body is not None:
                                self.ir.add(oid, arm, f"{self.ir.path}::op:{body.start_byte}:{body.end_byte}:{body.type}", ev)
        indexed_call = self.go_indexed_call(node, scope, cls)
        if indexed_call is not None:
            container, index = indexed_call
            cid = self.value(node, scope, cls)
            entry = self.entity("VALUE", "indexed-callee", cid, node)
            self.ir.add(scope, "HAS_CALL", cid, ev)
            self.ir.add(cid, "CALLEE_VALUE", entry, ev)
            self.ir.add(entry, "CONTAINER", container, ev)
            self.ir.add(entry, "INDEX", index, ev)
            self.ir.add(cid, "ARGUMENT", self.value(field(node, "operand"), scope, cls), ev, position=0, kind="positional")
        if kind == "arrow_function":
            body = field(node, "body")
            if body is not None and body.type != "statement_block":
                self.ir.add(scope, "RETURNS", self.value(body, scope, cls), ev)
                self.ir.add(scope, "BODY_VALUE", self.value(body, scope, cls), ev)
        if kind == "lambda_expression":
            body = field(node, "body")
            if body is not None and body.type not in {"block", "compound_statement", "statement_block"}:
                # Java/C# expression lambdas may target a void delegate. Keep
                # the body value without guessing the target's return contract.
                self.ir.add(scope, "BODY_VALUE", self.value(body, scope, cls), ev)
        if kind == "update_expression" and callable_scope:
            operand = field(node, "argument", "operand") or next(iter(node.named_children), None)
            if operand is not None:
                target = self.value(operand, scope, cls)
                self.ir.add(scope, "READS", target, ev)
                self.ir.add(scope, "WRITES", target, ev)
        if kind == "identifier" and callable_scope:
            value = self.resolve_name(self.text(node), scope)
            parent = node.parent
            # A declared name is bound, not read: Go's ``var x = 1`` spells the
            # name on a ``var_spec`` child, so the enclosing declaration is not
            # the identifier's direct parent.
            declared = self.declared_names(parent) if parent is not None else []
            defining = parent is not None and (parent.type in FUNCTIONS or node in declared
                                               or parent.type in ASSIGNMENTS and field(parent, "left", "name", "pattern") == node)
            if value and not defining and self.ir.entities[value].kind in {"STORAGE", "PARAMETER"}:
                self.ir.add(scope, "READS", value, ev)
        if kind in MEMBERS and callable_scope:
            value = self.value(node, scope, cls)
            if value in self.ir.entities and self.ir.entities[value].kind == "STORAGE":
                self.ir.add(scope, "READS", value, ev)
        if kind in {"augmented_assignment", "augmented_assignment_expression", "compound_assignment_expr"}:
            left, right = field(node, "left"), field(node, "right")
            if left is not None and right is not None:
                assignment_id = f"{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}"
                self.ir.add(assignment_id, "ASSIGNMENT_TARGET", self.value(left, scope, cls), ev)
                self.ir.add(assignment_id, "ASSIGNMENT_VALUE", self.value(right, scope, cls), ev)
        if kind in ASSIGNMENTS:
            if self.ir.language == 'cpp' and scope == cls and kind == 'field_declaration':
                for cpp_assignment, target, cpp_initial in self.cpp_field_initializers.get(node.id, []):
                    value = self.value(cpp_initial, scope, cls)
                    self.ir.add(cpp_assignment, 'ASSIGNMENT_TARGET', target, ev, basis='field-initializer')
                    self.ir.add(cpp_assignment, 'ASSIGNMENT_VALUE', value, ev, basis='field-initializer')
                    self.ir.add(target, 'ASSIGNED_FROM', value, ev)
                    self.ir.add(value, 'FLOWS_TO', target, ev)
                    self.ir.add(scope, 'WRITES', target, ev)
                    if value == 'NULL':self.ir.add(target, 'INITIALIZED_AS', 'NULL', ev)
                return  # Type/name normalization happened once during declaration collection.
            left, right = self.declaration_parts(node)
            if right is None and self.ir.language == "csharp" and kind == "variable_declarator":
                # This grammar leaves the initializer unfielded after '='.
                equal = next((i for i, c in enumerate(node.children) if c.type == "="), None)
                if equal is not None:
                    right = next((c for c in node.children[equal + 1:] if c.is_named and c.type != "comment"), None)
            if kind == "field_declaration" and left is not None and left.type == "variable_declarator":
                return  # The child handles initialization; don't emit a phantom field.
            if kind == "field_declaration" and left is None:
                return
            if left is not None:
                left = self.unwrap(left)
                if left.type == "function_declarator":
                    return
                if (self.ir.language in {'javascript', 'typescript'} and scope == cls
                        and kind in {'field_definition', 'public_field_definition'}
                        and left.type in {'property_identifier', 'private_property_identifier'}):
                    # A field declares its own slot, even beside a same-named
                    # method or inside a class nested in another lexical scope.
                    field_key = (scope, self.text(left))
                    known = self.names.get(field_key)
                    if known is not None and self.ir.entities[known].kind != 'STORAGE':
                        del self.names[field_key]
                    self.storage(self.text(left), scope, left)
                # Go spells the declared name on a ``var_spec``/``const_spec``
                # child, so the declaration node itself is the assignment. A Go
                # ``var`` inside a callable is a new binding even when the module
                # declares the same spelling: merging the two would make a
                # per-invocation slot share the write set of a file-scope one.
                go_declaration = self.ir.language == 'go' and kind in {'var_declaration', 'const_declaration'}
                if (left.type == 'identifier' and self.ir.entities[scope].kind == 'CALLABLE'
                        and (self.ir.language == 'python' and kind == 'assignment'
                             or self.ir.language in {'javascript', 'typescript', 'java', 'csharp'}
                             and kind == 'variable_declarator'
                             or go_declaration)):
                    # An explicit local declaration (or Python assignment) must
                    # not resolve to a same-spelled class field in the outer scope.
                    # Existing parameters retain their callable-local identity.
                    name = self.text(left)
                    wrapper = node.parent
                    block = self.block_scope(left)
                    if (block is not None and not self.is_body_block(block)
                            and (go_declaration or wrapper is not None
                                 and wrapper.type in BLOCK_DECLARATIONS.get(self.ir.language, set()))
                            and (scope, name) in self.names):
                        # A block-scoped declaration shadowing an enclosing binding
                        # of this callable. Give it its own entity: sharing the
                        # outer ``STORAGE`` would merge two different write sets.
                        self.block_storage(name, scope, block, left)
                    else:
                        self.storage(name, scope, left)
                target = self.value(left, scope, cls)
                if target in self.ir.entities:
                    self.ir.entities[target].attrs["declared"] = True
                if self.ir.language == 'cpp' and scope != cls and target in self.ir.entities:
                    # A function-local ``static`` outlives the call that
                    # initialized it, so the slot is shared state rather than a
                    # per-call local. Without the specifier the two shapes are
                    # indistinguishable downstream.
                    declaration = node.parent if node.parent is not None and node.parent.type == 'declaration' else None
                    if declaration is not None and any(
                            c.type == 'storage_class_specifier' and self.text(c) == 'static'
                            for c in declaration.children):
                        self.ir.entities[target].attrs["static"] = True
                        for f in self.ir.facts:
                            if f.subject == scope and f.object == target and f.relation == 'DECLARES':
                                f.attrs["static"] = True
                if scope == cls and target in self.ir.entities:
                    static = self.ir.language == "python" or bool(re.search(r"\bstatic\b", self.text(node.parent if node.parent and node.parent.type == "field_declaration" else node)))
                    if self.ir.language == 'csharp':
                        declaration = node
                        while declaration.type in {'variable_declarator', 'variable_declaration'} and declaration.parent:
                            declaration = declaration.parent
                        static = declaration.type == 'field_declaration' and any(
                            c.type == 'modifier' and self.text(c) in {'static', 'const'}
                            for c in declaration.named_children)
                        if declaration.type == 'event_field_declaration':
                            # A C# ``event`` is not a plain delegate field: it is a
                            # pair of add/remove accessors over its own backing store.
                            # Marking it lets a query separate a handler registration
                            # from an arithmetic ``+=`` on a delegate-typed field.
                            self.ir.entities[target].attrs['event'] = True
                            self.ir.add(cls, 'DECLARES_EVENT', target, ev, name=self.text(left))
                    if self.ir.language == 'python' and right is not None:
                        self.ir.entities[target].attrs['class_initialized'] = True
                    if self.ir.language == 'python' and right is None and field(node, 'type') is not None:
                        # A bare annotation does not assign a class attribute.
                        # Keep explicit ClassVar spelling as a class-level hint;
                        # this is syntax classification, not typing API resolution.
                        static = bool(self.ir.entities[target].attrs.get('class_initialized')
                                      or re.search(r'\bClassVar\s*\[', self.text(field(node, 'type'))))
                    self.ir.entities[target].attrs["static"] = static
                    for f in self.ir.facts:
                        if f.subject == cls and f.object == target and f.relation in {"HAS_FIELD", "DECLARES"}:
                            f.attrs["static"] = static
                annotation_node = field(node, "type")
                if annotation_node is None and node.parent:
                    annotation_node = field(node.parent, "type")
                if annotation_node is not None:
                    self.annotate_type(target, annotation_node, ev)
                if scope == cls and target in self.ir.entities:
                    from .field_initialization import record_field
                    record_field(self.ir, node, target, right is not None)
                if right:
                    value = self.value(right, scope, cls)
                    # Occurrence-level operands preserve successive assignments.
                    # The RHS is a syntax operand, not the computed stored value
                    # of compound assignment, destructuring or an overloaded setter.
                    assignment_id = f"{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}"
                    self.ir.add(assignment_id, "ASSIGNMENT_TARGET", target, ev)
                    self.ir.add(assignment_id, "ASSIGNMENT_VALUE", value, ev)
                    self.ir.add(target, "ASSIGNED_FROM", value, ev)
                    self.ir.add(value, "FLOWS_TO", target, ev)
                    self.ir.add(scope, "WRITES", target, ev)
                    if value == "NULL":
                        self.ir.add(target, "INITIALIZED_AS", "NULL", ev)
                    if self.enclosing(node, BRANCHES):
                        branch = self.enclosing(node, BRANCHES)
                        condition = field(branch, "condition")
                        # Associate the actual guard's storage, not any surrounding if.
                        guarded = any(self.value(n, scope, cls) == target for n in descendants(condition)
                                      if n.type in MEMBERS or n.type == "identifier") if condition else False
                        if guarded:
                            self.ir.add(target, "GUARDS_WRITE", scope, ev)
        if kind in CALLS:
            cid = self.value(node, scope, cls)
            if self.ir.language == "go" and kind == "composite_literal":
                for item in children(field(node, "body")):
                    if item.type != "keyed_element": continue
                    key, initial = field(item, "key"), field(item, "value")
                    if key is None or initial is None: continue
                    if key.type == "literal_element" and len(key.named_children) == 1: key = key.named_children[0]
                    if initial.type == "literal_element" and len(initial.named_children) == 1: initial = initial.named_children[0]
                    if key.type != "identifier": continue
                    initializer = f"{self.ir.path}::op:{item.start_byte}:{item.end_byte}:{item.type}"
                    self.ir.add(cid, "HAS_INITIALIZER", initializer, ev)
                    self.ir.add(initializer, "FIELD_NAME", self.text(key), ev)
                    self.ir.add(initializer, "STORES_VALUE", self.value(initial, scope, cls), ev)
            if self.ir.language == 'rust' and kind == 'struct_expression':
                for item in children(field(node, 'body')):
                    key = field(item, 'field')
                    initial = field(item, 'value')
                    if item.type == 'shorthand_field_initializer':
                        key = next((c for c in item.named_children if c.type == 'identifier'), None)
                        initial = key
                    if key is None or initial is None or key.type not in {'field_identifier', 'identifier'}:
                        continue
                    previous = item.prev_named_sibling
                    attributed = (previous is not None and previous.type == 'attribute_item'
                                  or any(c.type == 'attribute_item' for c in item.named_children))
                    attrs = {'modality': 'may'} if attributed else {}
                    initializer = f'{self.ir.path}::op:{item.start_byte}:{item.end_byte}:{item.type}'
                    self.ir.add(cid, 'HAS_INITIALIZER', initializer, self.evidence(item), **attrs)
                    self.ir.add(initializer, 'FIELD_NAME', self.text(key), self.evidence(item), **attrs)
                    self.ir.add(initializer, 'STORES_VALUE', self.value(initial, scope, cls), self.evidence(item), **attrs)
            self.call_nodes[cid] = node
            function = field(node, "function", "constructor", "type", "name")
            if kind == 'constructor_initializer':
                # ``: base(...)`` spells its callee as an unnamed token, so no field
                # lookup finds it.
                function = next((c for c in node.children if c.type in {'base', 'this'}), None)
            receiver_node = field(node, "object")
            name = self.text(function)
            if function is not None and function.type in MEMBERS:
                receiver_node, name = self.member_parts(function)
            elif function is not None and function.type == 'conditional_access_expression':
                # C# ``receiver?.Member(args)``: the null-conditional access is the
                # callee, so its two named parts are the receiver and the member.
                parts = function.named_children
                if len(parts) == 2:
                    receiver_node, name = parts[0], self.text(parts[1]).lstrip('.')
            receiver = self.value(receiver_node, scope, cls) if receiver_node is not None else ""
            self.ir.add(scope, "HAS_CALL", cid, ev)
            self.ir.add(cid, "CALLEE_NAME", name, ev)
            callee_expression = self.unwrap(function) if function is not None else None
            if callee_expression is not None and callee_expression.type in CALLS:
                self.ir.add(cid, "INVOKES_RESULT_OF", self.value(callee_expression, scope, cls), ev)
            binding_expression = function
            while binding_expression is not None and binding_expression.type == 'parenthesized_expression':
                inner = [c for c in binding_expression.named_children if 'comment' not in c.type]
                if len(inner) != 1:
                    break
                binding_expression = inner[0]
            if receiver_node is None and binding_expression is not None and binding_expression.type == "identifier":
                callee_value = self.resolve_name(self.text(binding_expression), scope)
                if callee_value is not None:
                    self.ir.add(cid, "CALLEE_VALUE", callee_value, ev)
            elif binding_expression is not None and binding_expression.type in MEMBERS | INDEXES:
                callee_value = self.value(binding_expression, scope, cls)
                self.ir.add(cid, "CALLEE_VALUE", callee_value, ev)
            # Go range binds its first slot to a map key (or an array index).
            # Keep this distinct from value iteration: map-as-set registries
            # notify the keys, whereas map payloads are unrelated values.
            loop = self.enclosing(node, LOOPS)
            if self.ir.language == "go" and loop is not None:
                clause = next((c for c in loop.named_children if c.type == "range_clause"), None)
                bindings = field(clause, "left")
                iterable = field(clause, "right")
                first = next(iter(children(bindings)), None)
                invoked = receiver_node if receiver_node is not None else function
                if first is not None and iterable is not None and self.text(first) != "_" and self.value(first, scope, cls) == self.value(invoked, scope, cls):
                    self.ir.add(scope, "ITERATES_KEYS_CALLS", self.value(iterable, scope, cls), ev)
                slots = children(bindings)
                if len(slots) == 2 and iterable is not None and self.text(slots[1]) != "_" and self.value(slots[1], scope, cls) == self.value(invoked, scope, cls):
                    collection = self.value(iterable, scope, cls)
                    self.ir.add(scope, "ITERATES_CALLS", collection, ev, name=name)
                    self.ir.add(cid, "ITERATED_CALL", collection, ev)
            self.ir.entities[cid].attrs.update(name=name, owner=scope,
                                               construction=kind in {"new_expression", "object_creation_expression", "struct_expression", "composite_literal"})
            if receiver:
                self.ir.add(cid, "RECEIVER", receiver, ev)
                self.ir.add(scope, "DELEGATES_TO", receiver, ev, name=name)
                if self.enclosing(node, LOOPS):
                    loop = self.enclosing(node, LOOPS)
                    iterable = field(loop, "right", "value", "iterable")
                    loop_var = loop_binding(loop)
                    if iterable and loop_var and self.value(loop_var, scope, cls) == receiver:
                        self.ir.add(scope, "ITERATES_CALLS", self.value(iterable, scope, cls), ev, name=name)
                        self.ir.add(cid, "ITERATED_CALL", self.value(iterable, scope, cls), ev)
                if self.enclosing(node, BRANCHES):
                    self.ir.add(scope, "CONDITIONAL_DELEGATION", receiver, ev, name=name)
            # Direct callback invocation in a foreach loop is distinct from
            # invoking a method on each element, but both preserve the iterable.
            loop = self.enclosing(node, LOOPS)
            if loop is not None and function is not None and not receiver:
                iterable = field(loop, "right", "value", "iterable")
                loop_var = loop_binding(loop)
                if iterable is not None and loop_var is not None and self.value(loop_var, scope, cls) == self.value(function, scope, cls):
                    self.ir.add(scope, "ITERATES_CALLS", self.value(iterable, scope, cls), ev, name="<callback>")
            arguments = field(node, "arguments")
            for position, arg in enumerate(children(arguments)):
                spelling = self.text(arg)
                arg_kind = ("spread_named" if spelling.startswith("**") else "spread_positional" if spelling.startswith(("*", "..."))
                            else "named" if arg.type == "keyword_argument" or field(arg, "name") is not None and arg.type == "argument" else "positional")
                # Only argument wrappers expose their expression via 'value'.
                # A Python subscript also has that field, but it is the container,
                # not the indexed expression passed to the callee.
                valnode = field(arg, "value", "expression") if arg.type in {"keyword_argument", "argument"} else None
                if valnode is None and arg.type == "argument" and arg.named_children:
                    valnode = arg.named_children[-1]  # C# named argument: name and expression.
                if valnode is None and arg_kind.startswith("spread") and arg.named_children:
                    valnode = arg.named_children[-1]
                value = self.value(valnode or arg, scope, cls)
                self.ir.add(cid, "ARGUMENT", value, ev, position=position, kind=arg_kind, name=self.text(field(arg, "name")))
                if self.ir.language == "python" and not receiver and name == "next" and position == 0 and self.resolve_name("next", scope) is None:
                    self.ir.add(cid, "ADVANCES_ITERATOR", value, ev, model="python-next")
                if receiver and name in {"append", "add", "push", "push_back", "Add"} and position == 0:
                    self.ir.add(cid, "INSERTS_INTO", receiver, ev, model="collection-api-shape")
                    self.ir.add(cid, "INSERTED_VALUE", value, ev)
                # Go's ``append(slice, element)`` is a free function, not a method,
                # and is the language's canonical way to add to a slice.
                if (not receiver and self.ir.language == "go" and name == "append"
                        and position == 0 and len(children(arguments)) == 2):
                    self.ir.add(cid, "INSERTS_INTO", value, ev, model="collection-api-shape")
                    self.ir.add(cid, "INSERTED_VALUE", self.value(children(arguments)[1], scope, cls), ev)
                if receiver and value == f"{cls}/THIS":
                    self.ir.add(scope, "PASSES_SELF_TO", receiver, ev, name=name)
            # ``map.get(k)`` / ``map.put(k, v)`` are the non-subscript spelling of
            # ``map[k]``, and the canonical Java, C# and Go examples of a pool use
            # them. Without this model such a class shows a map field, a lookup and a
            # write that nothing connects, so Flyweight read 0/8 on the RefactoringGuru
            # corpora while the subscript spelling of the same pool was detected.
            #
            # The container has to be a member -- a field or a module-level storage --
            # because ``get`` on a local or a parameter is not a pool, and that is also
            # what keeps a property setter (one argument) out of ``MAP_WRITES``.
            if receiver and _member_storage(receiver):
                supplied = [self.argument_value(argument, scope, cls) for argument in children(arguments)]
                if name in MAP_READS and 1 <= len(supplied) <= 2:
                    self.ir.add(scope, "LOOKS_UP", receiver, ev, model="map-api-shape")
                    self.ir.add(cid, "LOOKS_UP", receiver, ev, model="map-api-shape")
                    # A read is an access like any subscript: it names the container
                    # and the index it reads at, so ``x = map.get(k)`` and
                    # ``x = map[k]`` describe the same fact and a query does not
                    # need a second spelling of the same clause.
                    self.ir.add(cid, "CONTAINER", receiver, ev, model="map-api-shape")
                    self.ir.add(cid, "INDEX", supplied[0], ev, model="map-api-shape")
                    if node.parent is not None and node.parent.type in RETURN_TYPES:
                        self.ir.add(scope, "RETURNS_LOOKUP", receiver, ev, model="map-api-shape")
                if name in MAP_WRITES and len(supplied) >= 2:
                    self.ir.add(scope, "WRITES_ELEMENT", receiver, ev, model="map-api-shape")
                    self.ir.add(cid, "WRITES_ELEMENT", receiver, ev, model="map-api-shape")
                    self.ir.add(cid, "CONTAINER", receiver, ev, model="map-api-shape")
                    self.ir.add(cid, "INDEX", supplied[0], ev, model="map-api-shape")
                    self.ir.add(cid, "STORES_VALUE", supplied[1], ev, model="map-api-shape")

        if kind in INDEXES:
            base = field(node, "value", "object", "argument", "operand", "array") or next(iter(node.named_children), None)
            container = self.value(base, scope, cls)
            self.ir.add(scope, "LOOKS_UP", container, ev)
            if node.parent and node.parent.type in {"return_statement", "return_expression"}:
                self.ir.add(scope, "RETURNS_LOOKUP", container, ev)
            if node.parent and node.parent.type in ASSIGNMENTS and field(node.parent, "left") == node:
                self.ir.add(scope, "WRITES_ELEMENT", container, ev)
            key = field(node, "index", "subscript", "indices")
            if key is not None and key.type in {"bracketed_argument_list", "subscript_argument_list"}:
                keys = [c for c in key.named_children if c.type not in {"comment", "line_comment", "block_comment"}]
                key = self.unwrap(keys[0]) if len(keys) == 1 else None
            if key is None and self.ir.language == "rust" and kind == "index_expression" and len(node.named_children) == 2:
                key = node.named_children[1]
            if key is not None:
                access = self.value(node, scope, cls)
                self.ir.add(access, "CONTAINER", container, ev)
                self.ir.add(access, "INDEX", self.value(key, scope, cls), ev)
            assignment = node.parent
            if assignment is not None and assignment.type == "expression_list":
                assignment = assignment.parent
            left = field(assignment, "left")
            if assignment is not None and assignment.type in ASSIGNMENTS and left is not None and self.unwrap(left) == node and key is not None:
                oid = f"{self.ir.path}::op:{assignment.start_byte}:{assignment.end_byte}:{assignment.type}"
                self.ir.add(oid, "WRITES_ELEMENT", container, ev)
                self.ir.add(oid, "INDEX", self.value(key, scope, cls), ev)
                right = field(assignment, "right", "value")
                if right is not None and any(c.type == "=" for c in assignment.children):
                    self.ir.add(oid, "STORES_VALUE", self.value(right, scope, cls), ev)
        if kind in {"return_statement", "return_expression"}:
            value_node = next(iter(node.named_children), None) or next((c for c in node.children if c.type == "this"), None)
            value = self.value(value_node, scope, cls)
            if value_node is not None:
                occurrence = f"{self.ir.path}::op:{node.start_byte}:{node.end_byte}:{kind}"
                self.ir.add(occurrence, "RETURN_OPERAND", value, ev)
            self.ir.add(scope, "RETURNS", value, ev)
            if value == f"{cls}/THIS":
                self.ir.add(scope, "RETURNS_SELF", cls, ev)
        # Rust's final block expression is an implicit return. Only the final
        # expression in a callable body is eligible, not a nested block's tail.
        if self.ir.language == "rust" and kind == "block" and node.parent and node.parent.type in FUNCTIONS:
            last = next(iter(reversed(node.named_children)), None)
            if last and last.type not in {"expression_statement", "let_declaration", "return_expression"}:
                value = self.value(last, scope, cls)
                self.ir.add(scope, "RETURNS", value, self.evidence(last))
                if value == f"{cls}/THIS":
                    self.ir.add(scope, "RETURNS_SELF", cls, self.evidence(last))
        if kind in {"import_from_statement", "import_statement", "import_declaration", "use_declaration"}:
            self.ir.add(self.module, "IMPORT_SYNTAX", self.text(node), ev, language=self.ir.language)
        if kind == "package_declaration" and self.ir.language == "java":
            package = re.search(r"\bpackage\s+([\w.]+)\s*;", self.text(node))
            if package:
                self.ir.entities[self.module].attrs["package"] = package[1]
        if kind in {"export_statement"}:
            self.ir.add(self.module, "EXPORT_SYNTAX", self.text(node), ev)


def lower_source(source: str | bytes, language: str, path: str = "snippet") -> IR:
    data = source.encode("utf-8") if isinstance(source, str) else source
    return Lowerer(data, language, path).lower()


def lower_file(path: Path, relative_path: str | None = None) -> IR:
    language = LANGUAGES.get(path.suffix.lower())
    if language is None:
        raise ValueError(f"unsupported structural file: {path}")
    return lower_source(path.read_bytes(), language, relative_path or path.name)
