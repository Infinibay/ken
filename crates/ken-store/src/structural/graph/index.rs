use super::{GraphValues, Result, StructuralError, StructuralStore, syntax};
use ken_program::{Entity, Fact, Operation, value::GraphValue as V};
use rusqlite::{
    OptionalExtension, Statement, Transaction, TransactionBehavior, params, types::Value as Sql,
};
use std::collections::BTreeSet;

#[derive(Clone, Debug, Default)]
pub struct FactFilter {
    pub relation: String,
    pub subject: Option<String>,
    pub object: Option<String>,
    pub attribute: Option<(String, String)>,
}
impl FactFilter {
    pub fn relation(relation: impl Into<String>) -> Self {
        Self {
            relation: relation.into(),
            ..Self::default()
        }
    }
}
#[derive(Clone, Debug, Default)]
pub struct EntityFilter {
    pub kind: Option<String>,
    pub owner: Option<String>,
    pub source_owner: Option<String>,
    pub local_id: Option<String>,
}
#[derive(Clone, Debug, Default)]
pub struct OperationFilter {
    pub kind: Option<String>,
    pub owner: Option<String>,
    pub local_id: Option<String>,
    pub ordinal: Option<i64>,
    pub region: Option<String>,
}
/// A READY graph pinned by its store. The pin lasts until store repinning/close.
/// The borrow prevents closing or repinning the store while a reader is live.
pub struct GraphIndex<'a> {
    pub(super) store: &'a StructuralStore,
    pub(super) graph: i64,
    snapshot: i64,
    pub path: String,
    pub language: String,
    pub metadata: V,
    pub capabilities: BTreeSet<String>,
    pub relations: BTreeSet<String>,
}
struct GraphHeader {
    snapshot: i64,
    path: String,
    language: String,
    metadata: i64,
}
impl<'a> GraphIndex<'a> {
    /// The pinned source reader; immutable access cannot repin or close the store.
    pub fn source_store(&self) -> &StructuralStore {
        self.store
    }
    pub fn check_snapshot(&self) -> Result<()> {
        self.store.check_pinned_snapshot(self.snapshot)
    }
    pub fn graph_id(&self) -> i64 {
        self.graph
    }
    pub fn snapshot_id(&self) -> i64 {
        self.snapshot
    }
    pub fn open(store: &'a mut StructuralStore, graph: i64) -> Result<Self> {
        Self::open_with_check(store, graph, || Ok(()))
    }
    pub fn open_with_check(
        store: &'a mut StructuralStore,
        graph: i64,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<Self> {
        check()?;
        let header = Self::header(store, graph)?;
        let snapshot = header.snapshot;
        store.pin_snapshot(snapshot)?;
        if !syntax::ready(store.connection(), graph)? {
            let tx =
                Transaction::new_unchecked(store.connection(), TransactionBehavior::Immediate)?;
            syntax::ensure_atomic(&tx, graph, &mut || {
                check()?;
                store.renew(false)
            })?;
            tx.commit()?;
        }
        check()?;
        Self::read_metadata(store, graph, header)
    }
    /// Borrow an already prepared and pinned revision without creating a write scope.
    pub fn open_retained(store: &'a StructuralStore, graph: i64) -> Result<Self> {
        let header = Self::header(store, graph)?;
        store.check_pinned_snapshot(header.snapshot)?;
        if !syntax::ready(store.connection(), graph)? {
            return Err(StructuralError::Invalid(
                "retained query graph is not prepared",
            ));
        }
        Self::read_metadata(store, graph, header)
    }
    fn header(store: &StructuralStore, graph: i64) -> Result<GraphHeader> {
        let row:Option<(i64,String,String,String,String,i64)>=store.connection().query_row("SELECT snapshot_id,path,language,version,view,metadata FROM k2_graphs g JOIN k2_graph_publications p USING(graph_id) WHERE graph_id=?1 AND ready=1",[graph],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional()?;
        let (snapshot, path, language, version, view, metadata) =
            row.ok_or(StructuralError::Missing(graph))?;
        if version != ken_program::IR_VERSION || view != "query" {
            return Err(StructuralError::Invalid("incompatible query graph"));
        }
        Ok(GraphHeader {
            snapshot,
            path,
            language,
            metadata,
        })
    }
    fn read_metadata(store: &'a StructuralStore, graph: i64, header: GraphHeader) -> Result<Self> {
        let GraphHeader {
            snapshot,
            path,
            language,
            metadata,
        } = header;
        let values = GraphValues::new(store.connection(), graph);
        let metadata = values.get(metadata)?;
        let capabilities = store
            .connection()
            .prepare("SELECT capability FROM k2_graph_capabilities WHERE graph_id=?1")?
            .query_map([graph], |r| r.get(0))?
            .collect::<rusqlite::Result<_>>()?;
        let relations = if let V::Dict(items) = &metadata {
            items
                .iter()
                .find(|(k, _)| k.to_utf8().as_deref() == Some("relations"))
                .and_then(|(_, v)| {
                    if let V::List(items) = v {
                        Some(items.iter().filter_map(V::string).collect())
                    } else {
                        None
                    }
                })
                .unwrap_or_default()
        } else {
            return Err(StructuralError::Invalid("invalid query graph metadata"));
        };
        Ok(Self {
            store,
            graph,
            snapshot,
            path,
            language,
            metadata,
            capabilities,
            relations,
        })
    }
    pub fn find(store: &'a mut StructuralStore, key: &str) -> Result<Option<Self>> {
        let graph=store.connection().query_row("SELECT g.graph_id FROM k2_graphs g JOIN k2_graph_publications p USING(graph_id) WHERE fingerprint=?1 AND ready=1",[key],|r|r.get(0)).optional()?;
        graph.map(|id| Self::open(store, id)).transpose()
    }
    pub(super) fn values(&self) -> GraphValues<'_> {
        GraphValues::new(self.store.connection(), self.graph)
    }
    fn fact_query(&self, filter: &FactFilter) -> Result<(String, Vec<Sql>)> {
        let v = self.values();
        let mut args = vec![Sql::Integer(self.graph)];
        let access = if filter.subject.is_some() {
            "forward"
        } else if filter.attribute.is_some() {
            "attribute"
        } else if filter.object.is_some() {
            "reverse"
        } else {
            "relation"
        };
        let mut sql =
            format!(" FROM k2_graph_facts f INDEXED BY k2_graph_fact_{access} WHERE f.graph_id=?");
        for (column, value) in [
            ("relation", Some(filter.relation.as_str())),
            ("subject", filter.subject.as_deref()),
            ("object", filter.object.as_deref()),
        ] {
            if let Some(value) = value {
                let Some(id) = v.lookup(value)? else {
                    sql.push_str(" AND 0");
                    continue;
                };
                sql.push_str(&format!(" AND f.{column}=?"));
                args.push(Sql::Integer(id));
            }
        }
        if let Some((key, comparison)) = &filter.attribute {
            let key_id = v.lookup(key)?.unwrap_or(-1);
            let comparison_id = v.lookup(comparison)?.unwrap_or(-1);
            if filter.subject.is_some() || filter.object.is_some() {
                sql.push_str(" AND (EXISTS(SELECT 1 FROM k2_graph_members m WHERE m.graph_id=f.graph_id AND m.parent=f.attributes AND m.key=? AND m.comparison=?)");
                args.extend([key_id, comparison_id].map(Sql::Integer));
                if filter.relation == "OPERATION" {
                    if let Some((column, _)) = operation_column(key) {
                        if let Some(target) = attribute_target(&v, key, comparison)? {
                            sql.push_str(&format!(" OR EXISTS(SELECT 1 FROM k2_graph_operation_attributes a JOIN k2_graph_operations o ON o.graph_id=a.graph_id AND o.ordinal=a.operation_ordinal WHERE a.graph_id=f.graph_id AND a.fact_ordinal=f.ordinal AND {column}=?)"));
                            args.push(Sql::Integer(target));
                        }
                    } else {
                        sql.push_str(" OR EXISTS(SELECT 1 FROM k2_graph_operation_attributes a JOIN k2_graph_members m ON m.graph_id=a.graph_id AND m.parent=a.residual WHERE a.graph_id=f.graph_id AND a.fact_ordinal=f.ordinal AND m.key=? AND m.comparison=?)");
                        args.extend([key_id, comparison_id].map(Sql::Integer));
                    }
                }
                sql.push(')');
                return Ok((sql, args));
            }
            sql.push_str(" AND f.attributes IN (SELECT parent FROM k2_graph_members WHERE graph_id=? AND key=? AND comparison=?");
            args.extend([self.graph, key_id, comparison_id].map(Sql::Integer));
            if filter.relation == "OPERATION" {
                let column = operation_column(key);
                if let Some((column, access)) = column {
                    let target = attribute_target(&v, key, comparison)?;
                    if let Some(target) = target {
                        if key == "kind" {
                            sql.push_str(" UNION ALL SELECT -a.fact_ordinal-1 FROM k2_graph_operation_attributes a INDEXED BY k2_graph_operation_attributes_kind WHERE a.graph_id=? AND a.kind=?");
                        } else {
                            let hint = if access.is_empty() {
                                String::new()
                            } else {
                                format!(" INDEXED BY k2_graph_operation_{access}")
                            };
                            sql.push_str(&format!(" UNION ALL SELECT -a.fact_ordinal-1 FROM k2_graph_operations o{hint} JOIN k2_graph_operation_attributes a INDEXED BY k2_graph_operation_attributes_operation ON a.graph_id=o.graph_id AND a.operation_ordinal=o.ordinal WHERE o.graph_id=? AND {column}=?"));
                        }
                        args.extend([self.graph, target].map(Sql::Integer));
                    }
                } else {
                    sql.push_str(" UNION ALL SELECT -a.fact_ordinal-1 FROM k2_graph_operation_attributes a INDEXED BY k2_graph_operation_attributes_residual WHERE a.graph_id=? AND a.residual IN (SELECT parent FROM k2_graph_members WHERE graph_id=? AND key=? AND comparison=?)");
                    args.extend([self.graph, self.graph, key_id, comparison_id].map(Sql::Integer));
                }
            }
            sql.push(')');
        }
        Ok((sql, args))
    }
    pub fn facts(&self, filter: &FactFilter) -> Result<FactScan<'_>> {
        self.store.renew_reader()?;
        let (sql, args) = self.fact_query(filter)?;
        Ok(FactScan{decode:decode_fact,statement:self.store.connection().prepare(&format!("SELECT f.subject,f.relation,f.object,f.attributes,f.evidence{sql} ORDER BY f.ordinal"))?,args,store:self.store,graph:self.graph})
    }
    pub fn count(&self, filter: &FactFilter) -> Result<u64> {
        self.store.renew_reader()?;
        if filter.subject.is_none() && filter.object.is_none() && filter.attribute.is_none() {
            let Some(term) = self.values().lookup(&filter.relation)? else {
                return Ok(0);
            };
            let count: Option<i64> = self
                .store
                .connection()
                .query_row(
                    "SELECT count FROM k2_graph_relations WHERE graph_id=?1 AND relation=?2",
                    params![self.graph, term],
                    |r| r.get(0),
                )
                .optional()?;
            return Ok(count.unwrap_or(0) as u64);
        }
        let (sql, args) = self.fact_query(filter)?;
        Ok(self.store.connection().query_row(
            &format!("SELECT count(*){sql}"),
            rusqlite::params_from_iter(args),
            |r| r.get::<_, i64>(0),
        )? as u64)
    }
    pub fn exists(&self, filter: &FactFilter) -> Result<bool> {
        self.store.renew_reader()?;
        let (sql, args) = self.fact_query(filter)?;
        Ok(self.store.connection().query_row(
            &format!("SELECT EXISTS(SELECT 1{sql} LIMIT 1)"),
            rusqlite::params_from_iter(args),
            |r| r.get(0),
        )?)
    }
    pub fn entities(&self, filter: &EntityFilter) -> Result<EntityScan<'_>> {
        self.store.renew_reader()?;
        let mut sql="SELECT e.local_id,e.kind,e.name,e.path,e.line,e.end_line,e.attributes FROM k2_graph_entities e WHERE e.graph_id=?".to_owned();
        let mut args = vec![Sql::Integer(self.graph)];
        for (k, v) in [
            ("kind", &filter.kind),
            ("owner", &filter.owner),
            ("source_owner", &filter.source_owner),
            ("local_id", &filter.local_id),
        ] {
            self.term_filter(&mut sql, &mut args, "e", k, v.as_deref())?;
        }
        sql.push_str(" ORDER BY e.ordinal");
        Ok(EntityScan {
            decode: decode_entity,
            statement: self.store.connection().prepare(&sql)?,
            args,
            store: self.store,
            graph: self.graph,
        })
    }
    pub fn operations(&self, filter: &OperationFilter) -> Result<OperationScan<'_>> {
        self.store.renew_reader()?;
        let mut sql="SELECT o.local_id,o.kind,o.native_kind,o.parent,o.role,o.start_byte,o.end_byte,o.line,o.owner,o.attributes FROM k2_graph_operations o".to_owned();
        if filter.ordinal.is_none() {
            let access = if filter.local_id.is_some() {
                Some("id")
            } else if filter.owner.is_some() {
                Some("owner")
            } else if filter.kind.is_some() {
                Some("kind")
            } else if filter.region.is_some() {
                Some("id")
            } else {
                None
            };
            if let Some(access) = access {
                sql.push_str(&format!(" INDEXED BY k2_graph_operation_{access}"));
            }
        }
        let mut args = vec![Sql::Integer(self.graph)];
        sql.push_str(" WHERE o.graph_id=?");
        for (k, v) in [
            ("kind", &filter.kind),
            ("owner", &filter.owner),
            ("local_id", &filter.local_id),
        ] {
            self.term_filter(&mut sql, &mut args, "o", k, v.as_deref())?;
        }
        if let Some(ordinal) = filter.ordinal {
            sql.push_str(" AND o.ordinal=?");
            args.push(Sql::Integer(ordinal));
        }
        if let Some(region) = &filter.region {
            if let Some((start, end, _)) = self.syntax_bounds(region)? {
                sql.push_str(" AND o.local_id IN (SELECT local_id FROM k2_graph_syntax WHERE graph_id=? AND position>=? AND position<?)");
                args.extend([
                    Sql::Integer(self.graph),
                    Sql::Integer(start),
                    Sql::Integer(end),
                ]);
            } else {
                sql.push_str(" AND 0");
            }
        }
        sql.push_str(" ORDER BY o.ordinal");
        Ok(OperationScan {
            decode: decode_operation,
            statement: self.store.connection().prepare(&sql)?,
            args,
            store: self.store,
            graph: self.graph,
        })
    }
    fn term_filter(
        &self,
        sql: &mut String,
        args: &mut Vec<Sql>,
        alias: &str,
        column: &str,
        value: Option<&str>,
    ) -> Result<()> {
        if let Some(value) = value {
            if let Some(id) = self.values().lookup(value)? {
                sql.push_str(&format!(" AND {alias}.{column}=?"));
                args.push(Sql::Integer(id));
            } else {
                sql.push_str(" AND 0");
            }
        }
        Ok(())
    }
    pub fn syntax_bounds(&self, id: &str) -> Result<Option<(i64, i64, String)>> {
        self.store.renew_reader()?;
        let v = self.values();
        let Some(id) = v.lookup(id)? else {
            return Ok(None);
        };
        let row:Option<(i64,i64,i64)>=self.store.connection().query_row("SELECT position,subtree_end,final_node FROM k2_graph_syntax WHERE graph_id=?1 AND local_id=?2",params![self.graph,id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
        row.map(|(s, e, n)| Ok((s, e, v.word(n)?))).transpose()
    }
}

fn decode_fact(r: &rusqlite::Row<'_>, v: &GraphValues<'_>) -> Result<Fact> {
    let evidence = v.get(r.get(4)?)?;
    let V::List(items) = evidence else {
        return Err(StructuralError::Invalid("invalid fact evidence"));
    };
    Ok(Fact {
        subject: v.word(r.get(0)?)?,
        relation: v.word(r.get(1)?)?,
        object: v.word(r.get(2)?)?,
        attrs: v.get(r.get(3)?)?.into_attrs()?,
        evidence: items
            .into_iter()
            .map(|v| {
                v.string()
                    .ok_or(StructuralError::Invalid("invalid evidence string"))
            })
            .collect::<Result<_>>()?,
    })
}

fn decode_entity(r: &rusqlite::Row<'_>, v: &GraphValues<'_>) -> Result<Entity> {
    Ok(Entity {
        id: v.word(r.get(0)?)?,
        kind: v.word(r.get(1)?)?,
        name: r.get(2)?,
        path: v.word(r.get(3)?)?,
        line: r.get(4)?,
        end_line: r.get(5)?,
        attrs: v.get(r.get(6)?)?.into_attrs()?,
    })
}

fn decode_operation(r: &rusqlite::Row<'_>, v: &GraphValues<'_>) -> Result<Operation> {
    Ok(Operation {
        id: v.word(r.get(0)?)?,
        kind: v.word(r.get(1)?)?,
        native_kind: v.word(r.get(2)?)?,
        parent: r
            .get::<_, Option<i64>>(3)?
            .map(|id| v.word(id))
            .transpose()?,
        role: v.word(r.get(4)?)?,
        start: r.get(5)?,
        end: r.get(6)?,
        line: r.get(7)?,
        owner: v.word(r.get(8)?)?,
        attrs: v.get(r.get(9)?)?.into_attrs()?,
    })
}

/// A statement and its borrowed store; decoding and cancellation occur per row.
pub struct RecordScan<'a, T> {
    statement: Statement<'a>,
    args: Vec<Sql>,
    store: &'a StructuralStore,
    graph: i64,
    decode: fn(&rusqlite::Row<'_>, &GraphValues<'_>) -> Result<T>,
}
pub type FactScan<'a> = RecordScan<'a, Fact>;
pub type EntityScan<'a> = RecordScan<'a, Entity>;
pub type OperationScan<'a> = RecordScan<'a, Operation>;
impl<T> RecordScan<'_, T> {
    pub fn rows(&mut self) -> Result<impl Iterator<Item = Result<T>> + '_> {
        self.rows_checked(|| Ok(()))
    }
    pub fn rows_checked<'a>(
        &'a mut self,
        mut check: impl FnMut() -> Result<()> + 'a,
    ) -> Result<impl Iterator<Item = Result<T>> + 'a>
    where
        T: 'a,
    {
        let mut rows = self
            .statement
            .query(rusqlite::params_from_iter(&self.args))?;
        let store = self.store;
        let values = GraphValues::new(store.connection(), self.graph);
        let decode = self.decode;
        let mut done = false;
        Ok(std::iter::from_fn(move || {
            if done {
                return None;
            }
            let result = (|| {
                check()?;
                store.renew_reader()?;
                rows.next()?.map(|r| decode(r, &values)).transpose()
            })();
            match result {
                Ok(Some(row)) => Some(Ok(row)),
                Ok(None) => {
                    done = true;
                    None
                }
                Err(e) => {
                    done = true;
                    Some(Err(e))
                }
            }
        }))
    }
}

fn operation_column(key: &str) -> Option<(&'static str, &'static str)> {
    match key {
        "kind" => Some(("a.kind", "kind")),
        "native_kind" => Some(("o.native_kind", "native_kind")),
        "owner" => Some(("o.owner", "owner")),
        "role" => Some(("o.role", "")),
        "start_byte" => Some(("o.start_byte", "")),
        "end_byte" => Some(("o.end_byte", "")),
        _ => None,
    }
}
fn attribute_target(v: &GraphValues<'_>, key: &str, comparison: &str) -> Result<Option<i64>> {
    if matches!(key, "start_byte" | "end_byte") {
        Ok(comparison
            .parse::<i64>()
            .ok()
            .filter(|n| n.to_string() == comparison))
    } else {
        v.lookup(comparison)
    }
}
