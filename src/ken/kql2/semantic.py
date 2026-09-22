"""Demanded project linking, retaining contextual facts by immutable snapshot."""
from __future__ import annotations

import json
from typing import Callable, Iterator

from ken.structural.model import Fact
from ken.structural.type_refs import TypeRef
from ken.structural.semantic import link_project
from ken.structural_store import Node, Store
from ken.structural_store.leases import renew
from .values import QueryValue, Unknown, OperationValue

def _local_id(value: QueryValue) -> str | None:
    """The stable fact identity of a binding: a Node or an operation reference."""
    local = getattr(value,'local_id',None)
    return local if isinstance(local,str) and local else None


RELATIONS = {
    'possible_call':('POSSIBLE_CALL','Callable','Callable'),
    'returns_new':('RETURNS_NEW','Callable','TypeDecl'),
    'overrides':('OVERRIDES','Callable','Callable'),
    'subtype':('SUBTYPE_OF','TypeDecl','TypeDecl'),
    'nominal_root':('NOMINAL_ROOT','TypeDecl','TypeDecl'),
    'implements':('IMPLEMENTS','TypeDecl','TypeDecl'),
    # ``element_type($collection, $unit)``: the collection's element type is that
    # type (``ELEMENT_TYPE``). It is what separates a traversal of the component's
    # own children from a walk over an unrelated payload.
    'element_type':('ELEMENT_TYPE','Field','TypeDecl'),
    'returns_value':('RETURNS_VALUE','Callable','Value'),
    'final_member_input':('FINAL_MEMBER_INPUT','Operation','Parameter'),
    # ``final_field_value($write, $read)``: the write that ends the field's flow is
    # the one whose value is that read. A later overwrite leaves the field holding
    # something else, so the assignment stops being the final value.
    'final_field_value':('FINAL_FIELD_VALUE','Operation','Value'),
    'returns_self':('RETURNS_SELF','Callable','TypeDecl'),
    'returns_type':('RETURNS','Callable','TypeDecl'),
    'reads':('READS','Callable','Field'),
    'writes_element':('WRITES_ELEMENT','Callable','Field'),
    'iterates_calls':('ITERATES_CALLS','Callable','Field'),
    'writes':('WRITES','Callable','Field'),
    'delegates_to':('DELEGATES_TO','Callable','Field'),
    # ``guarded_write($field, $access)``: the accessor writes that storage under a guard
    # that references the storage itself -- a null/undefined test, an ``is_none()`` call
    # or any other form the frontend publishes as GUARDS_WRITE. A guard on an unrelated
    # flag publishes no such fact.
    'guarded_write':('GUARDS_WRITE','Field','Callable'),
    'forwards_slot':('FORWARDS_SLOT','Callable','Callable'),
    # ``advances($call, $place)``: this call advances that stored cursor --
    # ``ADVANCES_ITERATOR(call, storage)``, the delegation evidence of the
    # cursor protocol (Python ``next(self.values)``).
    'advances':('ADVANCES_ITERATOR','Call','Field'),
    # ``declares_event($unit, $event)``: the type publishes that storage as a C#
    # event (``DECLARES_EVENT``). A delegate-typed field never gets the fact, so
    # ``+=`` on a plain field is not a handler registration.
    'declares_event':('DECLARES_EVENT','TypeDecl','Field'),
    # ``subscribes($method, $event)`` / ``unsubscribes($method, $event)``: the
    # method registers a handler on the event (``+=``) or removes one (``-=``).
    'subscribes':('ADDS_HANDLER','Callable','Field'),
    'unsubscribes':('REMOVES_HANDLER','Callable','Field'),
    # ``raises($method, $event)``: the method contains a call that invokes the
    # event. The IR keys the fact by the call, so the join is published as
    # ``METHOD_RAISES_EVENT`` (see :func:`raised_events`) and read here.
    'raises':('METHOD_RAISES_EVENT','Callable','Field'),
    # ``effective($unit, $member)``: the member the unit *effectively* sees -- declared
    # by the unit or inherited through the single-inheritance chain
    # (``EFFECTIVE_METHOD``). An inherited registration is what an adapter registry
    # relies on, and the fact is absent as soon as the subclass shadows that operation
    # with a field, a property or an unrelated base.
    'effective':('EFFECTIVE_METHOD','TypeDecl','Callable'),
    # ``access_input($place, $parameter)``: the place is reached from that parameter
    # through member accesses and local aliases (``ACCESS_INPUT``). It is the claim
    # behind an index key derived from the request the method was entered with, as
    # opposed to a key the method names directly.
    'access_input':('ACCESS_INPUT','Value','Parameter'),
}

# One-argument predicates over the analysis status of a callable. ``supported``
# means the linear analysis proved the write inventory; a branch, an indirect write
# or an unresolved scope publishes ``unsupported`` with a reason.

UNARY_RELATIONS = {
    'linear_members':('MEMBER_FLOW_STATUS','supported'),
    'linear_bindings':('BINDING_FLOW_STATUS','supported'),
}

# Statement containment: what a pattern states when it correlates the regions the
# source nests. Each name is the claim it checks -- a statement inside a protected
# region, a loop that encloses it, a handler that protects it -- and lowers onto the
# relation the frontend already publishes, so a catalogue never names a raw relation
# nor walks the syntax tree to restate one.
STATEMENT_RELATIONS: dict[str, str] = {
    'inside_try': 'IN_TRY_BODY',
    'inside_handler': 'IN_HANDLER',
    'enclosed_by': 'ENCLOSING_LOOP',
    'handles': 'HANDLER_OF',
    'continues_to': 'CONTINUE_TARGET',
    'ends_with': 'LOOP_BODY_TAIL',
    'falls_through': 'HANDLER_FALLTHROUGH',
    # ``runs($callable, $operation)``: the operation belongs to that callable and is
    # reachable. The attribute is what keeps an unreachable operation from satisfying
    # the claim, exactly as the public ``possible_call`` family does.
    'runs': 'HAS_OPERATION',
    # ``returns_operand($return, $call)``: the call the return statement hands back.
    'returns_operand': 'SYNTAX_PARENT',
}

STATEMENT_ATTRS: dict[str, tuple[tuple[str, str, str], ...]] = {
    'runs': (('execution', 'literal', 'possible'),),
}

# A returned call may sit behind wrappers (``await``, a cast, a unary operator)
# before its syntax chain reaches the return statement, so the walk is bounded
# rather than a single relation lookup.
RETURN_OPERAND_HOPS = 4

STATEMENT_UNARY: dict[str, tuple[str, str]] = {
    'exits_cleanly': ('TRY_EXIT_STATUS', 'no-explicit-override'),
}


class SemanticRelations:
    def __init__(self, store: Store, snapshot: int, check: Callable[[], None]):
        self.store, self.snapshot, self.check = store, snapshot, check
        self.ready = False
        self.working: dict[tuple[str,str,str], list[Fact]] | None = None
        self.working_subjects: dict[tuple[str,str],list[Fact]] = {}
        self.types: dict[str,QueryValue] = {}

    def prepare(self) -> None:
        if self.ready:
            return
        store = self.store
        self.check()
        if store.db.execute('SELECT 1 FROM k2_analysis WHERE snapshot_id=?',(self.snapshot,)).fetchone():
            self.ready = True
            return
        units = []
        for (unit,) in store.db.execute('SELECT unit_id FROM k2_snapshot_units WHERE snapshot_id=?',(self.snapshot,)):
            self.check()
            units.append(store.load_unit(unit))
        # The catalog reads the query view (results, argument values, type
        # families); materialize the same facts here so both paths agree on what a
        # saved rule and a standalone query can see.
        from ken.structural.query_view import query_graph
        graph = query_graph(link_project(units)).ir
        self.check()
        renew(store,force=True)
        try:
            with store.transaction():
                # Another reader can have materialized the same immutable input.
                if not store.db.execute('SELECT 1 FROM k2_analysis WHERE snapshot_id=?',(self.snapshot,)).fetchone():
                    store.db.execute('INSERT INTO k2_analysis VALUES (?,?,?)',
                        (self.snapshot,json.dumps(sorted(graph.capabilities)),json.dumps(graph.diagnostics)))
                    store.db.executemany('INSERT INTO k2_semantic_facts VALUES (?,?,?,?,?,?,?)',
                        ((self.snapshot,i,f.subject,f.relation,f.object,json.dumps(f.attrs),json.dumps(f.evidence)) for i,f in enumerate(graph.facts)))
        except MemoryError:
            # Retention failure does not remove facts from this evaluation.
            self.working = {}
            for fact in graph.facts:
                self.working.setdefault((fact.relation,fact.subject,fact.object),[]).append(fact)
                self.working_subjects.setdefault((fact.relation,fact.subject),[]).append(fact)
        self.ready = True

    def facts(self, relation: str, subject: str) -> list[Fact]:
        self.prepare()
        self.check()
        if self.working is not None:
            rows = self.working_subjects.get((relation,subject),[])
        else:
            rows = [Fact(subject,relation,obj,json.loads(context),json.loads(evidence)) for obj,context,evidence in self.store.db.execute(
                'SELECT object,context,evidence FROM k2_semantic_facts WHERE snapshot_id=? AND relation=? AND subject=?',
                (self.snapshot,relation,subject))]
        if relation != 'ARGUMENT':
            return rows
        # The query view publishes one argument occurrence per position. BODY consumes
        # the raw per-occurrence operand contract, so restore it losslessly here; the
        # catalog path does the same in source_execution.SourceSemantics.
        restored = []
        for argument in rows:
            attrs = next((f.attrs for f in self.facts('ENTITY',argument.object)), {})
            for value in self.facts('VALUE',argument.object):
                loads = list(self.facts('LOADED_FROM',value.object))
                raw = loads[0].object if len(loads) == 1 else value.object
                restored.append(Fact(subject,relation,raw,attrs,argument.evidence))
        return restored

    def facts_to(self, relation: str, object: str) -> list[Fact]:
        """Facts of ``relation`` whose *object* is ``object`` — the reverse lookup.

        A body clause reads a fact from the side it bound: ``DISCARDS_RESULT`` is
        published as ``(statement, call)``, and a call clause holds the call.
        """
        self.prepare()
        self.check()
        if self.working is not None:
            return [fact for (rel,_subject,obj),group in self.working.items()
                    if rel == relation and obj == object for fact in group]
        return [Fact(subject,relation,object,json.loads(context),json.loads(evidence))
                for subject,context,evidence in self.store.db.execute(
                    'SELECT subject,context,evidence FROM k2_semantic_facts'
                    ' WHERE snapshot_id=? AND relation=? AND object=?',
                    (self.snapshot,relation,object))]

    def operations(self, owner: Node | None = None) -> Iterator[QueryValue]:
        from ken.structural_store.operations import load
        units: Iterator[int]
        if owner is None:
            units = (row[0] for row in self.store.db.execute(
                'SELECT unit_id FROM k2_snapshot_units WHERE snapshot_id=?',(self.snapshot,)))
        else:
            units = iter((owner.unit,))
        for unit in units:
            self.check()
            ir = load(self.store,unit,owner.local_id if owner else None)
            for op in ir.operations:
                self.check()
                yield OperationValue(self.snapshot,op.id,op.kind.lower(),op.native_kind,
                    ir.path,op.line,op.owner,ir.language,str(op.attrs.get('execution','unknown')))

    def type_of(self, node: Node, *, returns: bool = False) -> QueryValue:
        refs = self.facts('RETURN_TYPE_REF' if returns else 'TYPE_REF',node.local_id)
        if not refs or any(f.attrs.get('basis') == 'missing-annotation' for f in refs):
            return Unknown('type_information_missing')
        if len({f.object for f in refs}) != 1:
            return Unknown('ambiguous_type_descriptor')
        descriptor = self.descriptor(refs[0].object)
        if isinstance(descriptor,TypeRef) and not returns and self.facts('TYPE',node.local_id):
            # A project declaration can shadow an annotation spelling such as
            # Python str or a container called List. Do not call it a primitive.
            return TypeRef('nominal',descriptor.native,descriptor.arguments)
        return descriptor

    def descriptor(self, key: str) -> QueryValue:
        if key in self.types:
            return self.types[key]
        # Reserve first so malformed cyclic descriptors remain unknown.
        self.types[key] = Unknown('type_descriptor_cycle')
        kinds = self.facts('TYPE_KIND',key)
        native = self.facts('TYPE_NATIVE',key)
        if len(kinds) != 1 or len(native) != 1:
            return Unknown('type_descriptor_missing')
        children = sorted(self.facts('TYPE_ARGUMENT',key),key=lambda f:f.attrs.get('position',0))
        args = tuple(self.descriptor(f.object) for f in children)
        if not all(isinstance(a,TypeRef) for a in args):
            return Unknown('type_argument_missing')
        def scalar(relation: str):
            values = self.facts(relation,key)
            return values[0].object if len(values) == 1 else None
        bits, signed, extent, rank = (scalar(r) for r in ('TYPE_BITS','TYPE_SIGNED','TYPE_EXTENT','TYPE_RANK'))
        ref = TypeRef(kinds[0].object,native[0].object,tuple(a for a in args if isinstance(a,TypeRef)),
                      int(bits) if bits else None, signed == 'true' if signed else None,
                      extent,int(rank) if rank else None,tuple(f.object for f in self.facts('TYPE_QUALIFIER',key)))
        self.types[key] = ref
        return ref

    def unary(self, name: str, arguments: tuple[QueryValue,...]) -> QueryValue:
        """Evaluate a one-argument analysis-status predicate for a callable."""
        self.prepare()
        self.check()
        (a,) = arguments
        if not isinstance(a,Node):
            return Unknown('semantic_argument_unknown')
        relation, expected = UNARY_RELATIONS[name]
        rows = self.facts(relation,a.local_id)
        if any(f.object == expected for f in rows):
            return True
        # No status fact means the analysis found nothing to inventory; that is not
        # the same as a proven linear body.
        return False if rows else Unknown('analysis_status_missing')

    def call(self, name: str, arguments: tuple[QueryValue,...]) -> QueryValue:
        self.prepare()
        self.check()
        a,b = arguments
        # A BODY alias binds an operation reference; both it and a Node carry the
        # stable local identity the fact table is keyed by.
        subject, target = _local_id(a), _local_id(b)
        if subject is None or target is None:
            return Unknown('semantic_argument_unknown')
        relation = RELATIONS[name][0]
        if self.working is not None:
            contexts = [f.attrs for f in self.working.get((relation,subject,target),())]
        else:
            contexts = [json.loads(row[0]) for row in self.store.db.execute(
                'SELECT context FROM k2_semantic_facts WHERE snapshot_id=? AND relation=? AND subject=? AND object=?',
                (self.snapshot,relation,subject,target))]
        if any(c.get('execution','possible') == 'possible' for c in contexts):
            return True
        if contexts:
            # The relation exists but the source cannot reach it: dead code.
            return False
        # A missing resolved destination is not a closed possible-target set.
        # Dynamic dispatch, unresolved imports and macros remain visible as U.
        return Unknown('open_semantic_relation')
