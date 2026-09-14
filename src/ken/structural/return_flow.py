"""Local binding snapshots in structured, loop-free callable bodies.

This pass does not build a CFG. Unsupported scopes keep the older structural
summary; RETURN_ORIGIN is emitted only for evaluated, explicit return operands.
"""
from collections import defaultdict
from hashlib import sha256

from .model import IR, Operation


def sequential_returns(graph: IR) -> dict[tuple[str, str], set[str]]:
    """Return precise overrides for (callable, operand) allocation summaries."""
    operations = {o.id: o for o in graph.operations}
    by_owner: dict[str, list[Operation]] = defaultdict(list)
    for op in graph.operations:
        by_owner[op.owner].append(op)
    targets = {f.subject: f.object for f in graph.facts if f.relation == 'ASSIGNMENT_TARGET'}
    values = {f.subject: f.object for f in graph.facts if f.relation == 'ASSIGNMENT_VALUE'}
    operands = {f.subject: f.object for f in graph.facts if f.relation == 'RETURN_OPERAND'}
    members = {f.subject: f.object for f in graph.facts if f.relation == 'MEMBER_OF'}
    allocations = {f.subject for f in graph.facts if f.relation == 'ALLOCATES_TYPE'}
    arguments_by_call: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for f in graph.facts:
        if f.relation == 'ARGUMENT':
            arguments_by_call[f.subject].append((f.attrs.get('position', 0), f.object))
    # Operation and entity IDs differ. Owner includes file/scope identity; byte
    # offsets alone collide routinely across project units. Build this once.
    call_ops = {(op.owner, op.start, op.end): op for op in graph.operations if op.kind == 'CALL'}
    entity_to_op = {
        eid: call_ops[span_key]
        for eid, entity in graph.entities.items()
        if entity.kind == 'CALL'
        and (span_key := (entity.attrs.get('owner'), entity.attrs.get('start_byte'),
                        entity.attrs.get('end_byte'))) in call_ops
    }
    op_to_entity = {op.id: eid for eid, op in entity_to_op.items()}
    arguments_by_op: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for entity_id, args in arguments_by_call.items():
        mapped_op = entity_to_op.get(entity_id)
        if mapped_op is not None:
            arguments_by_op[mapped_op.id].extend(args)
    assigned: dict[str, set[str]] = defaultdict(set)
    for fact in graph.facts:
        if fact.relation == 'ASSIGNED_FROM':
            assigned[fact.subject].add(fact.object)
    locals_by_owner: dict[str, set[str]] = defaultdict(set)
    nested = set()
    dynamic = set()
    for f in graph.facts:
        if f.relation == 'DECLARES' and graph.entities[f.object].kind == 'STORAGE':
            locals_by_owner[f.subject].add(f.object)
        if f.relation == 'OWNED_BY' and graph.entities[f.subject].kind == 'CALLABLE':
            nested.add(f.object)
        if f.relation == 'CALLEE_NAME' and f.object in {'eval', 'exec', 'locals', 'globals', '_getframe', 'currentframe'}:
            dynamic.add(graph.entities[f.subject].attrs.get('owner'))
    result: dict[tuple[str, str], set[str]] = {}
    containers = {'expression_statement', 'lexical_declaration', 'variable_declaration',
                  'local_variable_declaration', 'local_declaration_statement', 'declaration',
                  'return_statement'}
    blocked_kinds = {'LOOP', 'TRY', 'THROW', 'YIELD', 'AWAIT', 'RESOURCE_SCOPE', 'MATCH', 'IMPORT', 'EXPORT'}
    blocked_native = {'global_statement', 'nonlocal_statement', 'delete_statement',
                      'update_expression', 'augmented_assignment', 'augmented_assignment_expression',
                      'goto_statement', 'labeled_statement', 'lock_statement', 'unsafe_statement',
                      'synchronized_statement', 'named_expression', 'ERROR'}
    for owner, ops in by_owner.items():
        entity = graph.entities[owner]
        if entity.kind != 'CALLABLE':
            continue
        return_ops = [o for o in ops if o.id in operands]
        if not return_ops and not any(o.id in arguments_by_op for o in ops):
            continue
        member_writes = {o.id: targets[o.id] for o in ops if o.id in targets
                         and members.get(targets[o.id]) in locals_by_owner[owner]}

        def opaque_field_rhs(op: Operation) -> bool:
            if op.native_kind not in {'conditional_expression', 'ternary_expression'}:
                return False
            current = op
            for _ in range(32):
                parent = operations.get(current.parent or '')
                if parent is None:
                    break
                if parent.id in member_writes:
                    return current.role in {'right', 'value'}
                current = parent
            return False

        reason = ''
        if graph.diagnostics:
            reason = 'diagnostics'
        elif entity.attrs.get('language') not in {'python', 'javascript', 'typescript', 'java', 'csharp'}:
            reason = 'language'
        elif owner in nested or owner in dynamic:
            reason = 'nested-or-dynamic-execution'
        elif any(o.kind in blocked_kinds or o.native_kind in blocked_native
                 or (o.kind == 'BRANCH' and o.native_kind != 'if_statement' and not opaque_field_rhs(o))
                 or any(t in {'ref', 'out', 'unsafe', '++', '--', '+=', '-=', '*=', '/=', '%=',
                              '&=', '|=', '^=', '<<=', '>>=', '??=', '&&=', '||='}
                        for t in o.attrs.get('tokens', [])) for o in ops):
            reason = 'control-or-indirect-write'
        bodies = [o for o in ops if o.role == 'body' and o.parent in operations
                  and operations[o.parent].kind == 'FUNCTION']
        if len(bodies) != 1:
            reason = reason or 'body'
        body_id = bodies[0].id if len(bodies) == 1 else ''

        branches = [o for o in ops if o.native_kind in {'if_statement', 'elif_clause'}]
        arms: dict[str, dict[str, str]] = {o.id: {} for o in branches}
        alternatives: dict[str, list[str]] = defaultdict(list)
        for op in ops:
            if op.parent in arms and op.role == 'consequence':
                arms[op.parent][op.role] = op.id
            if op.parent in arms and op.role == 'alternative':
                alternatives[op.parent].append(op.id)
        for parent, chain in alternatives.items():
            chain.sort(key=lambda op_id: operations[op_id].start)
            arms[parent]['alternative'] = chain[0]
            for current, following in zip(chain, chain[1:]):
                if current in arms:
                    arms[current]['alternative'] = following
                else:
                    reason = reason or 'branch-grammar'
        regions = {body_id} | {arm for pair in arms.values() for arm in pair.values()}

        def region_for(op: Operation) -> str | None:
            current: Operation | None = op
            while current is not None:
                if current.id in regions:
                    return current.id
                parent = operations.get(current.parent or '')
                if parent is not None and parent.id not in regions and parent.native_kind not in containers | {'else_clause'}:
                    enclosing = operations.get(parent.parent or '')
                    if not (parent.native_kind in {'block', 'statement_block'} and enclosing is not None
                            and enclosing.native_kind == 'else_clause' and enclosing.id in regions):
                        return None
                current = parent
            return None

        writes = [o for o in ops if o.id in targets]
        if any((targets[o.id] not in locals_by_owner[owner] and o.id not in member_writes) or region_for(o) is None
               or any(t.endswith('=') and t not in {'=', ':='} for t in o.attrs.get('tokens', [])) for o in writes):
            reason = reason or 'nonlocal-or-nested-write'
        exits = [o for o in ops if o.native_kind == 'return_statement']
        if any(region_for(o) is None for o in [*exits, *branches]):
            reason = reason or 'nested-return'
        if any('consequence' not in pair for pair in arms.values()):
            reason = reason or 'branch-grammar'
        # A write grammar omitted by the operand projection cannot be ignored.
        if any(o.kind == 'ASSIGN' and o.id not in targets for o in ops):
            reason = reason or 'unmodeled-assignment'
        # Block-scoped shadowing (P1.1). The frontend keys a local by
        # ``(owner, name)``, so two declarations with the same spelling in
        # different lexical blocks collapse into a single STORAGE. The branch
        # walk would then merge the writes of the inner and the outer binding
        # and report an origin that is not reachable at the read. Refuse with an
        # explicit reason instead of inventing that union. ``var`` (JS/TS
        # ``variable_declaration``) is function-scoped: both declarations really
        # are one binding, so the existing behaviour is kept for it.
        block_scopes = {'block', 'statement_block', 'compound_statement'}
        block_declarations = {
            'javascript': {'lexical_declaration'},
            'typescript': {'lexical_declaration'},
            'java': {'local_variable_declaration'},
            'csharp': {'variable_declaration'},
        }
        scoped_declarations = block_declarations.get(entity.attrs.get('language', ''), set())
        if scoped_declarations:
            declared_blocks: dict[str, set[str]] = defaultdict(set)
            for op in ops:
                if op.kind != 'ASSIGN' or op.native_kind != 'variable_declarator':
                    continue
                binding = targets.get(op.id)
                if binding is None or binding not in locals_by_owner[owner]:
                    continue
                wrapper, block = '', ''
                ancestor: Operation | None = operations.get(op.parent or '')
                for _ in range(64):
                    if ancestor is None:
                        break
                    if not wrapper and ancestor.native_kind in {'lexical_declaration', 'local_variable_declaration',
                                                                'variable_declaration', 'field_declaration'}:
                        wrapper = ancestor.native_kind
                    if ancestor.native_kind in block_scopes:
                        block = ancestor.id
                        break
                    ancestor = operations.get(ancestor.parent or '')
                if wrapper in scoped_declarations and block:
                    declared_blocks[binding].add(block)
            if any(len(blocks) > 1 for blocks in declared_blocks.values()):
                reason = reason or 'shadowed-binding'
        if reason:
            graph.add(owner, 'RETURN_FLOW_STATUS', 'unsupported', analysis='structured-locals/3', reason=reason)
            continue
        # Sets retain origin/write correlation; alias assignment replaces only
        # the immediate reaching write, while snapshotting its current origins.
        Case = tuple[str | None, str | None]
        Environment = dict[str | tuple[str, str], set[Case]]
        unknown: set[Case] = {(None, None)}
        pending: dict[str, set[Case]] = {o.id: set() for o in return_ops}
        arg_pending: dict[str, dict[tuple[int, str], set[Case]]] = defaultdict(lambda: defaultdict(set))
        field_returns: dict[tuple[str, str, str, str], int] = defaultdict(int)
        return_states: dict[str, int] = defaultdict(int)
        escaped: set[str] = set()
        if member_writes:
            # Only bare aliases, bare returns and member-write receivers are
            # modeled uses. Reject opaque publication/use, including helper([p]),
            # before traversing aliases: a container need not have value-flow facts.
            local_names = {graph.entities[b].name: b for b in locals_by_owner[owner]}
            for op in ops:
                binding = local_names.get(op.attrs.get('text', ''))
                if binding is None or op.native_kind not in {'identifier', 'variable_name'}:
                    continue
                immediate = operations.get(op.parent or '')
                if immediate is not None and immediate.kind == 'FUNCTION' and op.role == 'name':
                    continue  # The enclosing method's declaration is not a local use.
                if immediate is not None and immediate.kind == 'MEMBER' and op.role in {'attribute', 'property', 'field', 'name'}:
                    continue  # A member spelling is not a use of a same-named local.
                use_node = op
                allowed = False
                for _ in range(32):
                    use_parent = operations.get(use_node.parent or '')
                    if use_parent is None:
                        break
                    if use_parent.id in targets:
                        target = targets[use_parent.id]
                        allowed = ((target == binding and use_node.role in {'left', 'name'})
                                   or (values[use_parent.id] == binding and target in locals_by_owner[owner])
                                   or (use_parent.id in member_writes and use_node.role == 'left'
                                       and members[target] == binding))
                        break
                    if use_parent.id in operands:
                        allowed = operands[use_parent.id] == binding
                        break
                    use_node = use_parent
                if not allowed:
                    escaped.add(binding)
            todo = list(escaped)
            while todo:
                for source in assigned.get(todo.pop(), ()):
                    if source not in escaped:
                        escaped.add(source)
                        todo.append(source)
        events: dict[str, list[Operation]] = defaultdict(list)
        for op in [*writes, *exits, *branches]:
            region = region_for(op)
            if region is not None:
                events[region].append(op)
        def call_region(op: Operation) -> str | None:
            # Only eager, binding-effect-free expression wrappers are admitted.
            # Conditional/short-circuit expressions need their own region walk.
            current = op
            while current.id not in regions:
                parent = operations.get(current.parent or '')
                if parent is None:
                    return None
                if parent.id in regions:
                    return parent.id
                if not (parent.id in targets or parent.id in operands or parent.kind == 'CALL'
                        or parent.native_kind in containers | {
                            'argument_list', 'arguments', 'argument', 'parenthesized_expression'}):
                    return None
                current = parent
            return current.id

        for op in ops:
            if op.id in arguments_by_op:
                region = call_region(op)
                if region is not None:
                    events[region].append(op)
        for sequence in events.values():
            # Finish nested calls before their containing assignment/return;
            # branches instead enter their arms at the branch's start.
            sequence.sort(key=lambda op: (op.start if op.id in arms else op.end,
                                          0 if op.kind == 'CALL' else 1, -op.start))
        work = 0

        def snapshot(value: str, environment: Environment) -> set[Case]:
            if value in locals_by_owner[owner]:
                return environment.get(value, unknown)
            e = graph.entities.get(value)
            if e is not None and e.kind in {'STORAGE', 'MEMBER'}:
                return unknown
            return {(value, None)}

        def walk(region: str, environment: Environment, depth: int = 0) -> list[Environment]:
            nonlocal work
            if depth > 32:
                raise OverflowError('branch-depth')
            states = [dict(environment)]
            for op in events[region]:
                work += len(states)
                if work > 100000:
                    raise OverflowError('flow-work')
                continuing: list[Environment] = []
                if op.id in arms:
                    pair = arms[op.id]
                    for state in states:
                        continuing.extend(walk(pair['consequence'], state, depth + 1))
                        continuing.extend(walk(pair['alternative'], state, depth + 1) if 'alternative' in pair else [state])
                        if len(continuing) > 256:
                            raise OverflowError('flow-states')
                    if continuing and not member_writes:
                        merged: Environment = {}
                        for binding in set().union(*(state.keys() for state in continuing)):
                            cases = set().union(*(state.get(binding, unknown) for state in continuing))
                            work += len(cases)
                            if len(cases) > 256 or work > 100000:
                                raise OverflowError('flow-work')
                            merged[binding] = cases
                        continuing = [merged]
                elif op.id in targets:
                    for state in states:
                        if op.id in member_writes:
                            target = targets[op.id]
                            for origin, _ in snapshot(members[target], state):
                                if origin in allocations:
                                    assert origin is not None
                                    state[(origin, graph.entities[target].name)] = {(values[op.id], op.id)}
                        else:
                            state[targets[op.id]] = {(value, op.id) for value, _ in snapshot(values[op.id], state)}
                        continuing.append(state)
                else:
                    for state in states:
                        if op.id in operands:
                            return_states[op.id] += 1
                            cases = snapshot(operands[op.id], state)
                            pending[op.id].update(cases)
                            origins = {v for v, _ in cases if v in allocations and v not in escaped}
                            for slot, writes_at_slot in state.items():
                                if isinstance(slot, tuple) and slot[0] in origins:
                                    for _, write in writes_at_slot:
                                        if write is not None:
                                            field_returns[(op.id, slot[0], slot[1], write)] += 1
                        elif op.id in arguments_by_op:
                            for position, arg_storage in arguments_by_op[op.id]:
                                cases = snapshot(arg_storage, state)
                                arg_pending[op.id][(position, arg_storage)].update(cases)
                            continuing.append(state)
                states = continuing
                if not states:
                    break
            return states

        try:
            walk(body_id, {})
        except OverflowError as exc:
            reason = str(exc)
        if any(value is None for cases in pending.values() for value, _ in cases):
            reason = reason or 'unknown-binding'
        if reason:
            graph.add(owner, 'RETURN_FLOW_STATUS', 'unsupported', analysis='structured-locals/3', reason=reason)
            continue
        for op_id, cases in pending.items():
            op = operations[op_id]
            key = (owner, operands[op.id])
            result.setdefault(key, set())
            origins = {v for v, _ in cases}
            definitions = {d for _, d in cases}
            for value, definition in sorted(cases, key=lambda case: (case[0] or '', case[1] or '')):
                assert value is not None
                result[key].add(value)
                graph.add(op.id, 'RETURN_ORIGIN', value, f'{entity.path}:{op.line}',
                          basis='flow', analysis='structured-locals/3', modality='may' if len(origins) > 1 else 'must')
                if definition is not None:
                    graph.add(op.id, 'RETURN_REACHES', definition, f'{entity.path}:{op.line}',
                              basis='flow', analysis='structured-locals/3', modality='may' if len(definitions) > 1 else 'must')
        for op_id, by_argument in arg_pending.items():
            call_entity_id = op_to_entity[op_id]
            call_op = operations[op_id]
            for (position, storage_id), cases in sorted(by_argument.items()):
                known_cases = {(v, d) for v, d in cases if v is not None}
                has_unknown = any(v is None for v, _ in cases)
                origins = {v for v, _ in known_cases}
                argument_definitions = {d for _, d in known_cases if d is not None}
                graph.add(call_entity_id, 'ARGUMENT_ORIGIN', storage_id, f'{entity.path}:{call_op.line}',
                          basis='flow', analysis='argument-origins/1', position=position,
                          modality='must' if not has_unknown and len(origins) == 1 else 'may',
                          origins=sorted(origins), unknown=has_unknown,
                          cases=[list(case) for case in sorted(cases, key=lambda case: (case[0] or '', case[1] or ''))])
                for definition in sorted(argument_definitions):
                    graph.add(call_entity_id, 'ARGUMENT_REACHES', definition, f'{entity.path}:{call_op.line}',
                              basis='flow', analysis='argument-origins/1', position=position, operand=storage_id,
                              modality='may' if has_unknown or len(argument_definitions) > 1 else 'must')
        for (returned, origin, field, write), count in sorted(field_returns.items()):
            state_id = returned + '/field-state/' + sha256(repr((origin, field, write)).encode()).hexdigest()[:24]
            evidence = f'{entity.path}:{operations[write].line}'
            graph.add(returned, 'RETURN_FIELD_STATE', state_id, evidence,
                      analysis='structured-locals/3', basis='flow',
                      modality='must' if count == return_states[returned] else 'may', field=field)
            graph.add(state_id, 'FIELD_STATE_ORIGIN', origin, evidence)
            graph.add(state_id, 'FIELD_STATE_WRITE', write, evidence)
        graph.add(owner, 'RETURN_FLOW_STATUS', 'supported', analysis='structured-locals/3',
                  scope='explicit-returns-local-binding-origins')
    return result
