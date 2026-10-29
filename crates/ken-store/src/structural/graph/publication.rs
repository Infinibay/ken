use super::{GraphValues, Result, StructuralError, StructuralStore, leases, syntax};
use ken_program::{Attributes, Entity, Fact, Operation, StructuralIr, value::GraphValue as V};
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use std::{borrow::Cow, collections::BTreeMap};
const BATCH: usize = 32768;
type RecordStream<'a, T> = Box<dyn Iterator<Item = T> + 'a>;
type ProjectRecords<'a> = (
    RecordStream<'a, Entity>,
    RecordStream<'a, Operation>,
    RecordStream<'a, Fact>,
);
const CORE: [&str; 6] = [
    "kind",
    "native_kind",
    "owner",
    "role",
    "start_byte",
    "end_byte",
];
/// Borrowed publication copies only the record currently being encoded.
pub fn publish_graph(
    store: &mut StructuralStore,
    snapshot: i64,
    key: &str,
    ir: &StructuralIr,
    analysis: &V,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<i64> {
    publish(store, snapshot, key, Cow::Borrowed(ir), analysis, check)
}
/// Transfer private acquisition buffers; published records are released as written.
pub fn publish_graph_owned(
    store: &mut StructuralStore,
    snapshot: i64,
    key: &str,
    ir: StructuralIr,
    analysis: &V,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<i64> {
    publish(store, snapshot, key, Cow::Owned(ir), analysis, check)
}
fn checkpoint(
    store: &StructuralStore,
    graph: Option<i64>,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    if let Some(graph) = graph {
        let owner: Option<Option<String>> = store
            .connection()
            .query_row(
                "SELECT lease_id FROM k2_graph_publications WHERE graph_id=?1 AND ready=0",
                [graph],
                |r| r.get(0),
            )
            .optional()?;
        if owner.as_ref().map(|o| o.as_deref()) != Some(store.lease_id()) {
            return Err(StructuralError::Expired);
        }
        if let Some(lease) = store.lease_id() {
            let now = leases::now()?;
            store.connection().execute("INSERT INTO k2_leases VALUES(?1,?2,?3) ON CONFLICT(lease_id) DO UPDATE SET expires_ns=excluded.expires_ns WHERE k2_leases.expires_ns<=?4",params![lease,store.connection().query_row("SELECT snapshot_id FROM k2_graphs WHERE graph_id=?1",[graph],|r|r.get::<_,i64>(0))?,now+300_000_000_000,now])?;
        }
    }
    check()?;
    store.renew(false)
}
fn transaction<T>(
    store: &StructuralStore,
    graph: Option<i64>,
    check: &mut dyn FnMut() -> Result<()>,
    body: impl FnOnce(&Connection) -> Result<T>,
) -> Result<T> {
    let tx = Transaction::new_unchecked(store.connection(), TransactionBehavior::Immediate)?;
    checkpoint(store, graph, check)?;
    let out = body(&tx)?;
    if let Some(cap) = store.limit_bytes
        && store.allocated_bytes()? > cap
    {
        return Err(StructuralError::Retention);
    }
    tx.commit()?;
    Ok(out)
}
fn publish(
    store: &mut StructuralStore,
    snapshot: i64,
    key: &str,
    ir: Cow<'_, StructuralIr>,
    analysis: &V,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<i64> {
    if ir.view != "query" || ir.version != ken_program::IR_VERSION {
        return Err(StructuralError::Invalid(
            "expected compatible normalized query graph",
        ));
    }
    check()?;
    store.pin_snapshot(snapshot)?;
    let (graph, existing) = transaction(store, None, check, |db| {
        if let Some((id,ready,lease,old_snapshot))=db.query_row("SELECT g.graph_id,p.ready,p.lease_id,g.snapshot_id FROM k2_graphs g JOIN k2_graph_publications p USING(graph_id) WHERE fingerprint=?1",[key],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,bool>(1)?,r.get::<_,Option<String>>(2)?,r.get::<_,i64>(3)?))).optional()?{
            if ready{leases::pin(db,store.lease_id(),old_snapshot)?;return Ok((id,true));}
            let active:bool=db.query_row("SELECT EXISTS(SELECT 1 FROM k2_leases WHERE lease_id=?1 AND expires_ns>?2)",params![lease,leases::now()?],|r|r.get(0))?;
            if active{return Err(StructuralError::Invalid("query graph publication already in progress"));}
            db.execute("DELETE FROM k2_graphs WHERE graph_id=?1",[id])?;
        }
        db.execute("INSERT INTO k2_graphs(snapshot_id,fingerprint,path,language,version,view,metadata) VALUES(?1,?2,?3,?4,?5,?6,0)",params![snapshot,key,ir.path,ir.language,ir.version,ir.view])?;
        let id = db.last_insert_rowid();
        db.execute(
            "INSERT INTO k2_graph_publications VALUES(?1,0,?2)",
            params![id, store.lease_id()],
        )?;
        Ok((id, false))
    })?;
    if existing {
        return Ok(graph);
    }
    let result = (|| {
        let metadata = V::Dict(vec![
            (
                "diagnostics".into(),
                V::List(
                    ir.diagnostics
                        .iter()
                        .map(|s| V::String(s.as_str().into()))
                        .collect(),
                ),
            ),
            (
                "relations".into(),
                V::List(
                    ir.relations
                        .iter()
                        .map(|s| V::String(s.as_str().into()))
                        .collect(),
                ),
            ),
            ("entities".into(), V::Int(ir.entities.len().to_string())),
            ("operations".into(), V::Int(ir.operations.len().to_string())),
            ("facts".into(), V::Int(ir.facts.len().to_string())),
            (
                "analysis".into(),
                if analysis.truthy() {
                    analysis.clone()
                } else {
                    V::Dict(vec![])
                },
            ),
        ]);
        transaction(store, Some(graph), check, |db| {
            let v = GraphValues::new(db, graph);
            let id = v.put(&metadata)?;
            db.execute(
                "UPDATE k2_graphs SET metadata=?1 WHERE graph_id=?2",
                params![id, graph],
            )?;
            Ok(())
        })?;
        insert(
            store,
            graph,
            ir.capabilities.iter(),
            check,
            |v, _, capability| {
                v.db.execute(
                    "INSERT INTO k2_graph_capabilities VALUES(?1,?2)",
                    params![graph, capability],
                )?;
                Ok(())
            },
        )?;
        let mut owners = BTreeMap::new();
        for f in &ir.facts {
            if matches!(
                f.relation.as_str(),
                "DECLARES" | "HAS_PARAMETER" | "HAS_FIELD" | "HAS_METHOD"
            ) {
                owners.insert(f.object.clone(), f.subject.clone());
            }
        }
        for f in &ir.facts {
            if f.relation == "OWNED_BY" {
                owners.insert(f.subject.clone(), f.object.clone());
            }
        }
        let (entities, operations, facts): ProjectRecords<'_> = match ir {
            Cow::Borrowed(ir) => (
                Box::new(ir.entities.iter().map(|(_, e)| e.clone())),
                Box::new(ir.operations.iter().cloned()),
                Box::new(ir.facts.iter().cloned()),
            ),
            Cow::Owned(ir) => (
                Box::new(ir.entities.into_iter().map(|(_, e)| e)),
                Box::new(ir.operations.into_iter()),
                Box::new(ir.facts.into_iter()),
            ),
        };
        insert(store, graph, entities, check, |v, i, e| {
            let owner = string_attr(&e.attrs, "owner")?;
            let source = owners.get(&e.id).map(String::as_str).or(owner.as_deref());
            v.db.execute(
                "INSERT INTO k2_graph_entities VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
                params![
                    graph,
                    i,
                    v.term(&e.id)?,
                    v.term(&e.kind)?,
                    e.name,
                    v.term(&e.path)?,
                    e.line,
                    e.end_line,
                    v.put(&V::from_attrs(&e.attrs)?)?,
                    owner.as_deref().map(|s| v.term(s)).transpose()?,
                    int_attr(&e.attrs, "start_byte")?,
                    int_attr(&e.attrs, "end_byte")?,
                    source.map(|s| v.term(s)).transpose()?
                ],
            )?;
            Ok(())
        })?;
        drop(owners);
        insert(store, graph, operations, check, |v, i, o| {
            v.db.execute(
                "INSERT INTO k2_graph_operations VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
                params![
                    graph,
                    i,
                    v.term(&o.id)?,
                    v.term(&o.kind)?,
                    v.term(&o.native_kind)?,
                    o.parent.as_deref().map(|s| v.term(s)).transpose()?,
                    v.term(&o.role)?,
                    o.start,
                    o.end,
                    o.line,
                    v.term(&o.owner)?,
                    v.put(&V::from_attrs(&o.attrs)?)?
                ],
            )?;
            Ok(())
        })?;
        let mut counts = BTreeMap::<i64, i64>::new();
        insert(store, graph, facts, check, |v, i, f| {
            let relation = v.term(&f.relation)?;
            *counts.entry(relation).or_default() += 1;
            let attrs = operation_attrs(v, i, &f)?;
            v.db.execute(
                "INSERT INTO k2_graph_facts VALUES(?1,?2,?3,?4,?5,?6,?7)",
                params![
                    graph,
                    i,
                    v.term(&f.subject)?,
                    relation,
                    v.term(&f.object)?,
                    attrs,
                    v.put(&V::List(
                        f.evidence
                            .into_iter()
                            .map(|s| V::String(s.into()))
                            .collect()
                    ))?
                ],
            )?;
            Ok(())
        })?;
        insert(
            store,
            graph,
            counts.into_iter(),
            check,
            |v, _, (relation, count)| {
                v.db.execute(
                    "INSERT INTO k2_graph_relations VALUES(?1,?2,?3)",
                    params![graph, relation, count],
                )?;
                Ok(())
            },
        )?;
        publish_syntax(store, graph, check)?;
        transaction(store, Some(graph), check, |db| {
            db.execute(
                "UPDATE k2_graph_publications SET ready=1,lease_id=NULL WHERE graph_id=?1",
                [graph],
            )?;
            Ok(())
        })?;
        Ok(graph)
    })();
    if result.is_err() {
        let tx = Transaction::new_unchecked(store.connection(), TransactionBehavior::Immediate)?;
        tx.execute("DELETE FROM k2_graphs WHERE graph_id=?1 AND EXISTS(SELECT 1 FROM k2_graph_publications p WHERE p.graph_id=k2_graphs.graph_id AND p.ready=0 AND p.lease_id IS ?2)",params![graph,store.lease_id()])?;
        tx.commit()?;
    }
    result
}
fn insert<T>(
    store: &StructuralStore,
    graph: i64,
    mut items: impl Iterator<Item = T>,
    check: &mut dyn FnMut() -> Result<()>,
    mut put: impl FnMut(&GraphValues<'_>, i64, T) -> Result<()>,
) -> Result<()> {
    let mut ordinal = 0;
    loop {
        let tx = Transaction::new_unchecked(store.connection(), TransactionBehavior::Immediate)?;
        checkpoint(store, Some(graph), check)?;
        let values = GraphValues::new(&tx, graph);
        let mut done = false;
        for n in 0..BATCH {
            let Some(item) = items.next() else {
                done = true;
                break;
            };
            if n % 512 == 0 {
                checkpoint(store, Some(graph), check)?;
            }
            put(&values, ordinal, item)?;
            ordinal += 1;
        }
        if let Some(cap) = store.limit_bytes
            && store.allocated_bytes()? > cap
        {
            return Err(StructuralError::Retention);
        }
        tx.commit()?;
        if done {
            return Ok(());
        }
    }
}
fn string_attr(a: &Attributes, k: &str) -> Result<Option<String>> {
    a.get(k)
        .map(|r| {
            let v = V::parse(r)?;
            if matches!(v, V::Null) {
                Ok(None)
            } else {
                v.string()
                    .map(Some)
                    .ok_or(StructuralError::Invalid("expected string graph attribute"))
            }
        })
        .unwrap_or(Ok(None))
}
fn int_attr(a: &Attributes, k: &str) -> Result<Option<i64>> {
    a.get(k)
        .map(|r| {
            let v = V::parse(r)?;
            match v {
                V::Null => Ok(None),
                V::Int(s) => s
                    .parse()
                    .map(Some)
                    .map_err(|_| StructuralError::Invalid("graph integer column overflow")),
                _ => Err(StructuralError::Invalid("expected integer graph attribute")),
            }
        })
        .unwrap_or(Ok(None))
}
fn operation_attrs(v: &GraphValues<'_>, ordinal: i64, f: &Fact) -> Result<i64> {
    let fallback = || v.put(&V::from_attrs(&f.attrs)?);
    if f.relation != "OPERATION" || CORE.iter().any(|k| !f.attrs.contains_key(*k)) {
        return fallback();
    }
    let mut strings = Vec::new();
    for k in &CORE[..4] {
        let Ok(Some(s)) = string_attr(&f.attrs, k) else {
            return fallback();
        };
        strings.push(s);
    }
    let (Ok(Some(start)), Ok(Some(end))) = (
        int_attr(&f.attrs, "start_byte"),
        int_attr(&f.attrs, "end_byte"),
    ) else {
        return fallback();
    };
    let native = v.term(&strings[1])?;
    let owner = v.term(&strings[2])?;
    let role = v.term(&strings[3])?;
    let op:Option<i64>=v.db.query_row("SELECT ordinal FROM k2_graph_operations INDEXED BY k2_graph_operation_id WHERE graph_id=?1 AND local_id=?2 AND native_kind=?3 AND owner=?4 AND role=?5 AND start_byte=?6 AND end_byte=?7 ORDER BY ordinal LIMIT 1",params![v.graph,v.term(&f.subject)?,native,owner,role,start,end],|r|r.get(0)).optional()?;
    let Some(op) = op else { return fallback() };
    let residual: Attributes = f
        .attrs
        .iter()
        .filter(|(k, _)| !CORE.contains(&k.as_str()))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let residual = v.put(&V::from_attrs(&residual)?)?;
    v.db.execute(
        "INSERT INTO k2_graph_operation_attributes VALUES(?1,?2,?3,?4,?5)",
        params![v.graph, ordinal, op, v.term(&strings[0])?, residual],
    )?;
    Ok(-ordinal - 1)
}

fn publish_syntax(
    store: &StructuralStore,
    graph: i64,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    let mut intervals = syntax::Intervals::read(store.connection(), graph, &mut || {
        transaction(store, Some(graph), check, |_| Ok(()))
    })?;
    transaction(store, Some(graph), check, |db| {
        db.execute("INSERT INTO k2_graph_syntax_ready VALUES(?1)", [graph])?;
        Ok(())
    })?;
    loop {
        let tx = Transaction::new_unchecked(store.connection(), TransactionBehavior::Immediate)?;
        checkpoint(store, Some(graph), check)?;
        let mut done = false;
        for _ in 0..BATCH {
            let Some((id, start, end, last)) =
                intervals.next_checked(&mut || checkpoint(store, Some(graph), check))?
            else {
                done = true;
                break;
            };
            tx.execute(
                "INSERT INTO k2_graph_syntax VALUES(?1,?2,?3,?4,?5)",
                params![graph, id, start, end, last],
            )?;
        }
        if let Some(cap) = store.limit_bytes
            && store.allocated_bytes()? > cap
        {
            return Err(StructuralError::Retention);
        }
        tx.commit()?;
        if done {
            return Ok(());
        }
    }
}
