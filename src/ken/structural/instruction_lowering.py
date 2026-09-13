"""Tree-sitter operation adapter to the instruction core, with explicit opacity."""
from collections import defaultdict
from dataclasses import asdict

from .instructions import Function, Instruction, Operand, Program, Region
from .model import IR, Operation
from .type_refs import parse_type


BLOCKS = {'block', 'statement_block', 'compound_statement', 'statement_list', 'else_clause', 'constructor_body'}
WRAPPERS = {'expression_statement', 'parenthesized_expression', 'argument', 'expression_list', 'bracketed_argument_list'}
IDENTIFIERS = {'identifier', 'this', 'self'}


def type_data(native, language):
    def convert(value):
        if isinstance(value, dict): return {k: convert(v) for k, v in value.items()}
        if isinstance(value, tuple): return [convert(v) for v in value]
        return value
    return convert(asdict(parse_type(native, language)))


class Lowering:
    def __init__(self, graph: IR, entity, children, symbols, parameters, operators, optional_nodes):
        self.graph, self.entity, self.children = graph, entity, children
        self.function = Function(entity.id, entity.name, entity.attrs['language'], [], {}, Region(entity.id + '/entry', 'entry'))
        self.counter = 0
        self.active_depth = 0
        self.reasons: set[str] = set()
        self.symbols = symbols
        self.operators = operators
        self.optional_nodes = optional_nodes
        for param in parameters:
            self.function.parameters.append(self.place(param.name))
        if graph.diagnostics:
            self.reasons.add('source-diagnostics')

    def place(self, name):
        pid = self.entity.id + '/slot/' + name
        if pid not in self.function.places:
            symbol = self.symbols.get(name)
            native = symbol.attrs.get('native_type', '') if symbol else ''
            self.function.places[pid] = dict(name=name, type=type_data(native, self.function.language),
                source_symbol=symbol.id if symbol else None, scope='function' if symbol else 'unresolved')
            if symbol is None:
                self.reasons.add('unresolved-binding:' + name)
        return pid

    def emit(self, region, node, opcode, operands=(), *, result=True, effects=(), regions=(), **attrs):
        iid = self.entity.id + '/instruction/' + str(self.counter)
        self.counter += 1
        output = iid + '/value' if result else None
        operand_list = list(operands)
        result_type = {'kind': 'unknown', 'native': ''}
        if opcode == 'slot.load':
            result_type = self.function.places[operand_list[0].ref]['type']
        elif opcode in {'field.addr', 'index.addr'}:
            result_type = {'kind': 'address', 'native': ''}
        elif opcode == 'const':
            native = attrs.get('native_kind', node.native_kind)
            kind = ('bool' if native in {'true','false','boolean_literal'} else
                    'null' if native in {'null','none','null_literal'} else
                    'float' if 'float' in native or native == 'real_literal' else
                    'number' if native == 'number' else 'int' if 'int' in native else 'unknown')
            result_type = {'kind': kind, 'native': native}
        region.instructions.append(Instruction(iid, opcode, operand_list, output,
            dict(path=self.entity.path, start=node.start, end=node.end, line=node.line, operation=node.id),
            list(effects), attrs, list(regions), result_type))
        return Operand('value', output) if output is not None else None

    def opaque(self, node, region, reason):
        self.reasons.add(reason + ':' + node.native_kind)
        return self.emit(region, node, 'native', effects=['unknown'], native_kind=node.native_kind,
                         source_operation=node.id, reason=reason)

    def field(self, node, *roles):
        return next((c for role in roles for c in self.children[node.id] if c.role == role), None)

    def address(self, node, region):
        if node.native_kind in WRAPPERS and len(self.children[node.id]) == 1:
            return self.address(self.children[node.id][0], region)
        if node.native_kind in IDENTIFIERS:
            return Operand('place', self.place(node.attrs.get('text', node.native_kind)))
        if node.kind == 'MEMBER':
            receiver = self.field(node, 'object', 'value', 'expression', 'argument', 'operand')
            member = self.field(node, 'attribute', 'property', 'field', 'name')
            implicit_this = self.function.language == 'csharp' and node.attrs.get('tokens') == ['this', '.']
            if member is not None and (receiver is not None or implicit_this):
                base = self.expression(receiver, region) if receiver is not None else self.emit(
                    region, node, 'slot.load', [Operand('place', self.place('this'))], effects=['read.binding'], implicit_receiver=True)
                return self.emit(region, node, 'field.addr', [base], field=member.attrs.get('text', ''), effects=[])
        if node.native_kind in {'subscript', 'subscript_expression', 'element_access_expression', 'index_expression', 'array_access'}:
            receiver = self.field(node, 'value', 'object', 'argument', 'array', 'expression', 'operand')
            index = self.field(node, 'subscript', 'index', 'indices')
            if self.function.language == 'rust' and len(self.children[node.id]) == 2:
                receiver, index = self.children[node.id]
            if receiver is not None and index is not None:
                return self.emit(region, node, 'index.addr', [self.expression(receiver, region), self.expression(index, region)])
        return self.opaque(node, region, 'unknown-address')

    def expression(self, node, region, depth=0):
        if self.active_depth >= 64:
            return self.opaque(node, region, 'nesting-limit')
        self.active_depth += 1
        try:
            return self._expression(node, region, depth)
        finally:
            self.active_depth -= 1

    def _expression(self, node, region, depth=0):
        if depth > 64:
            return self.opaque(node, region, 'nesting-limit')
        if node.id in self.optional_nodes:
            return self.opaque(node, region, 'optional-evaluation')
        nested = self.children[node.id]
        if node.native_kind in WRAPPERS and len(nested) == 1:
            return self.expression(nested[0], region, depth + 1)
        if node.native_kind in IDENTIFIERS:
            return self.emit(region, node, 'slot.load', [self.address(node, region)], effects=['read.binding'])
        if node.kind == 'MEMBER' or node.native_kind in {'subscript', 'subscript_expression', 'element_access_expression', 'index_expression', 'array_access'}:
            return self.emit(region, node, 'memory.load', [self.address(node, region)], effects=['read.memory', 'unknown'], dispatch='native')
        if node.native_kind in {'conditional_expression', 'ternary_expression'}:
            condition = self.field(node, 'condition')
            consequence, alternative = self.field(node, 'consequence'), self.field(node, 'alternative')
            if self.function.language == 'python' and len(nested) == 3:
                consequence, condition, alternative = nested
            if condition is None or consequence is None or alternative is None:
                return self.opaque(node, region, 'conditional-expression')
            value = self.expression(condition, region, depth + 1)
            return self.emit(region, node, 'choose', [value], effects=['unknown'],
                regions=[self.value_region(consequence, 'consequence', depth + 1),
                         self.value_region(alternative, 'alternative', depth + 1)],
                truth='native', evaluation='selected-arm-only')
        if node.kind in {'BINARY', 'UNARY', 'COMPARE'}:
            operators = self.operators.get(node.id, [])
            if self.function.language == 'cpp' and node.kind in {'BINARY','COMPARE'}:
                return self.opaque(node, region, 'operator-evaluation-order')
            if len(operators) == 1 and operators[0] in {'and', 'or', '&&', '||', '??'}:
                left, right = self.field(node, 'left'), self.field(node, 'right')
                # User-defined C++/C# operators can change conditional evaluation.
                if left is None or right is None or self.function.language not in {'python','javascript','typescript','java','go','rust'}:
                    return self.opaque(node, region, 'conditional-operator-dispatch')
                value = self.expression(left, region, depth + 1)
                return self.emit(region, node, 'short_circuit', [value], effects=['unknown'],
                    regions=[self.value_region(right, 'rhs', depth + 1)], operator=operators[0],
                    result_policy='selected-operand' if self.function.language in {'python','javascript','typescript'} else 'boolean',
                    truth='nullish' if operators[0] == '??' else 'native')
            if len(operators) != 1:
                return self.opaque(node, region, 'conditional-or-chained-expression')
            operands = [c for c in nested if c.role != 'operator']
            return self.emit(region, node, node.kind.lower(), [self.expression(c, region, depth + 1) for c in operands],
                             operator=operators[0], effects=['unknown'])
        if node.kind == 'CALL':
            callee = self.field(node, 'function', 'constructor', 'type', 'name')
            arguments = self.field(node, 'arguments')
            args = self.children[arguments.id] if arguments else []
            if callee is None or any(c.native_kind in {'keyword_argument', 'list_splat', 'dictionary_splat', 'spread_element', 'named_argument'} for c in args):
                return self.opaque(node, region, 'call-binding')
            if self.function.language == 'cpp' and len(args) > 1:
                return self.opaque(node, region, 'argument-evaluation-order')
            receiver = self.field(node, 'object')
            member_call = callee.kind == 'MEMBER' or receiver is not None
            implicit_this = False
            if callee.kind == 'MEMBER':
                implicit_this = self.function.language == 'csharp' and callee.attrs.get('tokens') == ['this', '.']
                receiver = self.field(callee, 'object', 'value', 'expression', 'argument', 'operand')
                member = self.field(callee, 'attribute', 'property', 'field', 'name')
                if member is None:
                    return self.opaque(node, region, 'member-call')
                callee = member
            values = [self.expression(receiver, region)] if receiver else []
            if implicit_this and not values:
                values.append(self.emit(region, node, 'slot.load', [Operand('place', self.place('this'))], effects=['read.binding'], implicit_receiver=True))
            if values:
                values[0].role = 'receiver'
            # Member calls retain the receiver; a plain name is a symbol reference.
            if not member_call and callee.attrs.get('text') in self.symbols and self.function.language != 'java':
                bound_callee = self.expression(callee, region)
                bound_callee.role = 'callee'
                values.append(bound_callee)
            else:
                values.append(Operand('symbol', callee.attrs['text'], 'callee') if 'text' in callee.attrs else self.expression(callee, region))
            for position, argument in enumerate(args):
                value = self.expression(argument, region, depth + 1)
                value.role = 'argument:' + str(position)
                values.append(value)
            opcode = 'construct' if node.native_kind in {'new_expression', 'object_creation_expression'} else 'call'
            return self.emit(region, node, opcode, values, effects=['invoke', 'unknown'])
        if node.kind in {'YIELD', 'AWAIT'}:
            opcode = 'yield.delegate' if node.kind == 'YIELD' and node.attrs.get('delegated') else node.kind.lower()
            return self.emit(region, node, opcode, [self.expression(c, region, depth + 1) for c in nested], effects=['suspend', 'unknown'])
        if not nested and ('literal' in node.native_kind or node.native_kind in {'integer', 'float', 'number', 'true', 'false', 'none', 'null'}):
            return self.emit(region, node, 'const', spelling=node.attrs.get('text', ''), native_kind=node.native_kind)
        return self.opaque(node, region, 'expression-lowering')

    def region(self, node, kind):
        region = Region(node.id + '/region/' + kind, kind)
        self.statement(node, region)
        return region

    def value_region(self, node, kind, depth):
        region = Region(node.id + '/region/' + kind, kind)
        value = self.expression(node, region, depth)
        region.outputs = [value.ref]
        return region

    def branch(self, node, region, alternatives=None, depth=0):
        condition, consequence = self.field(node, 'condition'), self.field(node, 'consequence')
        if depth > 64 or condition is None or consequence is None:
            self.opaque(node, region, 'branch-lowering')
            return
        arms = [self.region(consequence, 'consequence')]
        rest = alternatives if alternatives is not None else [c for c in self.children[node.id] if c.role == 'alternative']
        if rest:
            alternative = Region(rest[0].id + '/region/alternative', 'alternative')
            if rest[0].native_kind == 'elif_clause':
                self.branch(rest[0], alternative, rest[1:], depth + 1)
            elif len(rest) == 1:
                self.statement(rest[0], alternative)
            else:
                self.opaque(node, region, 'ambiguous-branch-alternatives')
                return
            arms.append(alternative)
        value = self.expression(condition, region)
        self.emit(region, node, 'if', [value], result=False, regions=arms, truth='native', effects=['unknown'])

    def iteration(self, node, region):
        kind = node.native_kind
        if kind not in {'for_statement','for_in_statement','enhanced_for_statement','foreach_statement','for_expression'}:
            return False
        tokens = node.attrs.get('tokens', [])
        language = self.function.language
        supported = ((language == 'python' and kind == 'for_statement') or
                     (language in {'javascript','typescript'} and kind == 'for_in_statement' and 'of' in tokens) or
                     (language == 'java' and kind == 'enhanced_for_statement') or
                     (language == 'csharp' and kind == 'foreach_statement') or
                     (language == 'rust' and kind == 'for_expression'))
        target = self.field(node, 'left', 'name', 'pattern')
        source, body = self.field(node, 'right', 'value'), self.field(node, 'body')
        if not supported or any(t in {'async','await','ref'} for t in tokens) or self.field(node, 'alternative') is not None:
            return False
        if target is None or target.native_kind not in IDENTIFIERS or source is None or body is None:
            return False
        value = self.expression(source, region)
        repeated = Region(body.id + '/region/body', 'body')
        item = self.emit(repeated, target, 'iteration.value', effects=['unknown'])
        place = self.address(target, repeated)
        if language != 'python':
            self.emit(repeated, target, 'slot.declare', [place], result=False)
        self.emit(repeated, target, 'slot.store', [place, item], result=False, effects=['write.binding'])
        self.statement(body, repeated)
        self.emit(region, node, 'iterate', [value], result=False, regions=[repeated],
                  effects=['invoke','unknown'], protocol='native', element='value', evaluation='iterable-once')
        return True

    def statement(self, node, region, depth=0):
        if self.active_depth >= 64:
            self.opaque(node, region, 'nesting-limit')
            return
        self.active_depth += 1
        try:
            self._statement(node, region, depth)
        finally:
            self.active_depth -= 1

    def _statement(self, node, region, depth=0):
        if depth > 64 or node.owner != self.entity.id:
            self.opaque(node, region, 'nested-or-deep-region')
            return
        nested = self.children[node.id]
        kind = node.native_kind
        if kind in BLOCKS | {'expression_statement', 'local_variable_declaration', 'local_declaration_statement', 'lexical_declaration', 'variable_declaration', 'declaration'}:
            for child in nested:
                if child.role == 'type' or child.native_kind in {'modifiers', 'predefined_type', 'integral_type'}:
                    continue
                if kind == 'declaration' and child.role == 'declarator' and child.native_kind in IDENTIFIERS:
                    self.emit(region, child, 'slot.declare', [self.address(child, region)], result=False)
                else:
                    self.statement(child, region, depth + 1)
        elif node.kind == 'DECLARATION' and kind == 'variable_declarator':
            name = self.field(node, 'name')
            if name is not None and name.native_kind in IDENTIFIERS:
                self.emit(region, node, 'slot.declare', [self.address(name, region)], result=False)
            else:
                self.opaque(node, region, 'declaration-lowering')
        elif node.kind == 'ASSIGN' or kind == 'init_declarator':
            left = self.field(node, 'left', 'name', 'pattern', 'declarator')
            right = self.field(node, 'right', 'value')
            if right is None and left is not None and self.function.language == 'csharp' and '=' in node.attrs.get('tokens', []):
                right = next((c for c in nested if c.start >= left.end and c is not left), None)
            if left is None or right is None or any(t.endswith('=') and t not in {'=',':='} for t in node.attrs.get('tokens', [])):
                self.opaque(node, region, 'assignment-lowering')
                return
            if kind in {'variable_declarator','init_declarator','let_declaration'} and left.native_kind in IDENTIFIERS:
                self.emit(region, node, 'slot.declare', [self.address(left, region)], result=False)
            if self.function.language in {'python', 'cpp'}:
                value = self.expression(right, region)
                target = self.address(left, region)
            else:
                target = self.address(left, region)
                value = self.expression(right, region)
            binding = target.kind == 'place'
            self.emit(region, node, 'slot.store' if binding else 'memory.store', [target, value], result=False,
                      effects=['write.binding'] if binding else ['write.memory', 'unknown'])
        elif node.kind == 'RETURN':
            self.emit(region, node, 'return', [self.expression(c, region) for c in nested], result=False)
        elif kind in {'if_statement', 'if_expression'}:
            self.branch(node, region)
        elif node.kind == 'LOOP':
            if self.field(node, 'alternative') is not None:
                self.opaque(node, region, 'loop-exhaustion-clause')
                return
            if self.iteration(node, region):
                return
            condition, body = self.field(node, 'condition'), self.field(node, 'body')
            counted = kind == 'for_statement' and self.function.language in {'javascript','typescript','java','csharp','cpp'}
            if counted and condition is not None and condition.native_kind == 'empty_statement':
                condition = None
            if kind not in {'while_statement','do_statement'} and not counted or body is None or (condition is None and not counted):
                self.opaque(node, region, 'loop-lowering')
                return
            test = Region(node.id + '/region/test', 'test')
            value = self.expression(condition, test) if condition is not None else self.emit(
                test, node, 'const', spelling='true', native_kind='true', implicit=True)
            test.outputs = [value.ref]
            body_region = self.region(body, 'body')
            if counted:
                init, update = Region(node.id + '/region/init','init'), Region(node.id + '/region/update','update')
                for child in nested:
                    if child.role in {'init','initializer'}: self.statement(child, init)
                    elif child.role in {'update','increment'}: self.statement(child, update)
                regions, form = [init,test,body_region,update], 'for'
            elif kind == 'do_statement':
                regions, form = [body_region,test], 'do'
            else:
                regions, form = [test,body_region], 'while'
            self.emit(region, node, 'loop', result=False, regions=regions, form=form,
                      continue_region='update' if counted else 'test')
        elif kind in {'break_statement', 'continue_statement'} and not nested:
            self.emit(region, node, kind.removesuffix('_statement'), result=False)
        elif node.kind == 'THROW':
            self.emit(region, node, 'throw', [self.expression(c, region) for c in nested], result=False)
        elif kind in {'pass_statement', 'empty_statement'}:
            pass
        else:
            self.expression(node, region)


def lower_instructions(graph: IR) -> Program:
    if graph.view != 'source':
        raise ValueError('instruction lowering requires the source IR view')
    children: dict[str, list[Operation]] = defaultdict(list)
    by_owner: dict[str, list[Operation]] = defaultdict(list)
    symbols: dict[str, dict] = defaultdict(dict)
    parameters: dict[str, list] = defaultdict(list)
    operators: dict[str, list[str]] = defaultdict(list)
    optional_nodes: set[str] = set()
    parents = {op.id:op.parent for op in graph.operations}
    for op in graph.operations:
        if op.native_kind == 'optional_chain' or '?.' in op.attrs.get('tokens', []):
            current: str | None = op.id
            while current is not None and current not in optional_nodes:
                optional_nodes.add(current)
                current = parents.get(current)
    for entity in graph.entities.values():
        if entity.kind in {'PARAMETER', 'STORAGE'}:
            symbols[entity.id.rsplit('/', 1)[0]][entity.name] = entity
    for fact in graph.facts:
        if fact.relation == 'HAS_PARAMETER':
            parameters[fact.subject].append(graph.entities[fact.object])
        elif fact.relation == 'OPERATOR':
            operators[fact.subject].append(fact.object)
    for op in graph.operations:
        by_owner[op.owner].append(op)
        if op.parent and 'comment' not in op.native_kind:
            children[op.parent].append(op)
    for nodes in children.values():
        nodes.sort(key=lambda o: (o.start, o.end, o.id))
    functions = []
    for entity in sorted(graph.entities.values(), key=lambda e: e.id):
        if entity.kind != 'CALLABLE':
            continue
        lowering = Lowering(graph, entity, children, symbols[entity.id], parameters[entity.id], operators, optional_nodes)
        declarations = {o.id for o in by_owner[entity.id] if o.kind == 'FUNCTION'}
        for op in by_owner[entity.id]:
            if op.parent in declarations and op.native_kind in {'field_initializer_list','constructor_initializer'}:
                lowering.opaque(op, lowering.function.body, 'constructor-initialization')
        bodies = [o for o in by_owner[entity.id] if o.role == 'body' and o.parent in declarations]
        if len(bodies) == 1:
            body = bodies[0]
            if body.native_kind not in BLOCKS:
                value = lowering.expression(body, lowering.function.body)
                lowering.emit(lowering.function.body, body, 'return', [value], result=False, implicit=True)
            elif entity.attrs['language'] == 'rust' and children[body.id] and children[body.id][-1].native_kind not in {'expression_statement','let_declaration','return_expression'}:
                for statement in children[body.id][:-1]:
                    lowering.statement(statement, lowering.function.body)
                tail = children[body.id][-1]
                if tail.kind == 'LOOP':
                    lowering.statement(tail, lowering.function.body)
                else:
                    value = lowering.expression(tail, lowering.function.body)
                    lowering.emit(lowering.function.body, tail, 'return', [value], result=False, implicit=True)
            else:
                lowering.statement(body, lowering.function.body)
        else:
            lowering.reasons.add('missing-or-ambiguous-body')
        lowering.function.reasons = sorted(lowering.reasons)
        lowering.function.status = 'partial' if lowering.reasons else 'lowered'
        functions.append(lowering.function)
    result = Program(graph.version, functions)
    result.verify()
    return result
