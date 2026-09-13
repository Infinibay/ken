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
    call_callee_name: dict[str, str] = {}
    call_callee_value: dict[str, str] = {}
    for f in graph.facts:
        if f.relation == 'CALLEE_NAME':
            call_callee_name[f.subject] = f.object
        elif f.relation == 'CALLEE_VALUE':
            call_callee_value[f.subject] = f.object
    # ARGUMENT facts reference CALL entities (e.g. ``CALLABLE:m/CALL:316@316:340``)
    # whose native operation lives in ``operations`` under a separate op id
    # (e.g. ``op:316:340:call``). The entity id format is built in
    # ``frontend.entity`` as ``{scope}/CALL:{start_byte}@{start_byte}:{end_byte}``
    # (the @ separator follows the CALL name, which itself is the start byte —
    # see frontend.py around the ``CALL`` branch). Build a positional map so the
    # walk can reuse the existing region/event machinery instead of inventing a
    # parallel walker.
    entity_to_op: dict[str, Operation] = {}
    for op in graph.operations:
        if op.kind != 'CALL':
            continue
        suffix = f'/CALL:{op.start}@{op.start}:{op.end}'
        for eid, entity in graph.entities.items():
            if entity.kind != 'CALL':
                continue
            if eid.endswith(suffix):
                entity_to_op[eid] = op
                break
    arguments_by_op: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for entity_id, args in arguments_by_call.items():
        op = entity_to_op.get(entity_id)
        if op is not None:
            arguments_by_op[op.id].extend(args)
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
        if not return_ops:
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
        if reason:
            graph.add(owner, 'RETURN_FLOW_STATUS', 'unsupported', analysis='structured-locals/3', reason=reason)
            continue
        # Sets retain origin/write correlation; alias assignment replaces only
        # the immediate reaching write, while snapshotting its current origins.
        Case = tuple[str | None, str | None]
        Environment = dict[str | tuple[str, str], set[Case]]
        unknown: set[Case] = {(None, None)}
        pending: dict[str, set[Case]] = {o.id: set() for o in return_ops}
        arg_pending: dict[str, dict[str, set[Case]]] = defaultdict(lambda: defaultdict(set))
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
        for sequence in events.values():
            sequence.sort(key=lambda op: op.start)
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
                            # When the operand itself is a CALL (e.g. ``return
                            # writer.write(value)``) snapshot the call's arguments
                            # here: control flow would evaluate the call's
                            # arguments immediately before consuming the result,
                            # so the same state must drive both the return origin
                            # and the call-site argument provenance. Without this,
                            # the call op (visited after the return in event order)
                            # would never have its arguments evaluated because the
                            # walk terminates once the return clears ``states``.
                            operand_entity = operands[op.id]
                            call_op_for_operand = entity_to_op.get(operand_entity)
                            if call_op_for_operand is not None:
                                for _position, arg_storage in arguments_by_op.get(call_op_for_operand.id, ()):
                                    arg_pending[call_op_for_operand.id][arg_storage].update(snapshot(arg_storage, state))
                            origins = {v for v, _ in cases if v in allocations and v not in escaped}
                            for slot, writes_at_slot in state.items():
                                if isinstance(slot, tuple) and slot[0] in origins:
                                    for _, write in writes_at_slot:
                                        if write is not None:
                                            field_returns[(op.id, slot[0], slot[1], write)] += 1
                        elif op.id in arguments_by_op:
                            for _position, arg_storage in arguments_by_op[op.id]:
                                cases = snapshot(arg_storage, state)
                                arg_pending[op.id][arg_storage].update(cases)
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
        # Translate call op ids back to entity ids so kenql.query_graph can
        # consume the fact through the same subject it sees on ARGUMENT rows.
        arg_pending_by_entity: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        for op_id, by_storage in arg_pending.items():
            for entity_id, mapped in entity_to_op.items():
                if mapped.id == op_id:
                    arg_pending_by_entity[entity_id].update(by_storage)
                    break
        for call_entity_id, by_storage in arg_pending_by_entity.items():
            call_op = entity_to_op[call_entity_id]
            for storage_id, cases in sorted(by_storage.items(), key=lambda kv: kv[0]):
                known_cases = {(v, d) for v, d in cases if v is not None}
                # ``cases`` already carries the may/must distinction the walk
                # produced: an unknown binding (None) in any arm collapses the
                # modality to ``may`` because that arm contributes no producer
                # information, even if every known arm agrees on the same one.
                has_unknown = any(v is None for v, _ in cases)
                if not known_cases and not has_unknown:
                    continue
                definitions = {d for v, d in known_cases if d is not None}
                # Same-producer criterion: every reaching definition resolves to
                # the same producer callable (CALLEE for a CALL value, otherwise
                # the value itself for a literal/external source). Mixed known
                # sources, or known+unknown, stay 'may'.
                producer_keys: set[tuple[str, str]] = set()
                for value, _def in known_cases:
                    callee_value = call_callee_value.get(value)
                    callee_name = call_callee_name.get(value)
                    if callee_value is not None:
                        producer_keys.add(('CALLEE_VALUE', callee_value))
                    elif callee_name is not None:
                        producer_keys.add(('CALLEE_NAME', callee_name))
                    else:
                        producer_keys.add(('VALUE', value))
                producer_modality = 'must' if not has_unknown and len(producer_keys) == 1 else 'may'
                graph.add(call_entity_id, 'ARGUMENT_ORIGIN', storage_id, f'{entity.path}:{call_op.line}',
                          basis='flow', analysis='structured-locals/3', modality=producer_modality,
                          producer_keys=sorted(producer_keys))
                for definition in sorted(definitions):
                    graph.add(call_entity_id, 'ARGUMENT_REACHES', definition, f'{entity.path}:{call_op.line}',
                              basis='flow', analysis='structured-locals/3',
                              modality='may' if has_unknown or len(definitions) > 1 else 'must')
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
