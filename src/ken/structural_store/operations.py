"""Indexed syntactic contexts, separate from lexical scope and CFG semantics."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING
from ken.structural.model import IR, Entity, Operation

if TYPE_CHECKING:
    from .store import Store


def project(store: Store, unit: int, ir: IR) -> None:
    """Called inside the source unit transaction; payload remains lossless."""
    if store.db.execute('SELECT 1 FROM k2_operation_units WHERE unit_id=?',(unit,)).fetchone():
        return
    entities={(e.attrs.get('start_byte'),e.attrs.get('end_byte'),e.attrs.get('native_kind')):e.id
              for e in ir.entities.values() if e.kind in ('CALL','VALUE')}
    store.db.execute('INSERT INTO k2_operation_units VALUES (?)',(unit,))
    store.db.executemany('INSERT INTO k2_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        ((unit,o.id,o.owner,o.parent,o.kind,o.native_kind,o.role,o.start,o.end,o.line,
          json.dumps(o.attrs),entities.get((o.start,o.end,o.native_kind))) for o in ir.operations))


def load(store: Store, unit: int, owner: str | None = None) -> IR:
    """Read only one callable's operations; migrate old units lazily, once.

    Parent IDs and byte ranges describe syntax containment, not declaration
    visibility. In particular parentheses do not become lexical namespaces.
    """
    if not store.db.execute('SELECT 1 FROM k2_operation_units WHERE unit_id=?',(unit,)).fetchone():
        raw=store.load_unit(unit)
        try:
            with store.transaction():
                project(store,unit,raw)
        except MemoryError:
            raw.facts=[]
            if owner is not None:
                raw.operations=[o for o in raw.operations if o.owner==owner]
            spans={(o.start,o.end) for o in raw.operations}
            raw.entities={key:e for key,e in raw.entities.items() if e.kind in ('CALL','VALUE') and
                          (e.attrs.get('start_byte'),e.attrs.get('end_byte')) in spans}
            return raw
    row=store.db.execute('SELECT path,language FROM k2_units WHERE unit_id=?',(unit,)).fetchone()
    if row is None:
        raise KeyError(unit)
    ir=IR(row[0],row[1])
    sql='''SELECT local_id,owner,parent,kind,native_kind,role,start_byte,end_byte,line,attributes,entity_id
           FROM k2_operations WHERE unit_id=?'''
    params: tuple = (unit,)
    if owner is not None:
        sql+=' AND owner=?'
        params+=(owner,)
    sql+=' ORDER BY start_byte,end_byte DESC,local_id'
    for local_id,op_owner,parent,kind,native,role,start,end,line,attrs,entity_id in store.db.execute(sql,params):
        ir.operations.append(Operation(local_id,kind,native,parent,role,start,end,line,op_owner,json.loads(attrs)))
        if entity_id is not None:
            ir.entities[entity_id]=Entity(entity_id,'CALL' if kind=='CALL' else 'VALUE','',ir.path,line,line,
                {'start_byte':start,'end_byte':end,'owner':op_owner,'native_kind':native})
    return ir
