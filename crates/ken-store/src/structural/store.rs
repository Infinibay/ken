use super::{Result, Scalar, StructuralError, ast, leases, projection, schema};
use flate2::{Compression, read::ZlibDecoder, write::ZlibEncoder};
use ken_program::{Attributes, Entity, Operation, Program, StructuralIr};
use rusqlite::{
    Connection, OpenFlags, OptionalExtension, TransactionBehavior, params, types::Value as Sql,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct StoredNode {
    pub id: i64,
    pub unit: i64,
    pub local_id: String,
    pub kind: String,
    pub name: Option<String>,
    pub owner: Option<String>,
    pub line: i64,
    pub end_line: i64,
    pub path: String,
    pub language: String,
}
impl StoredNode {
    fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Self> {
        Ok(Self {
            id: r.get(0)?,
            unit: r.get(1)?,
            local_id: r.get(2)?,
            kind: r.get(3)?,
            name: r.get(4)?,
            owner: r.get(5)?,
            line: r.get(6)?,
            end_line: r.get(7)?,
            path: r.get(8)?,
            language: r.get(9)?,
        })
    }
}
#[derive(Clone, Debug, Default)]
pub struct NodeFilter {
    pub kind: Option<String>,
    pub name: Option<String>,
    pub owner: Option<(i64, String)>,
    pub node_id: Option<i64>,
    pub reference: bool,
}
impl NodeFilter {
    fn matches(&self, n: &StoredNode) -> bool {
        self.kind.as_ref().is_none_or(|k| k == &n.kind)
            && self
                .name
                .as_ref()
                .is_none_or(|name| n.name.as_ref().is_none_or(|v| v == name))
            && self
                .owner
                .as_ref()
                .is_none_or(|(u, o)| *u == n.unit && n.owner.as_ref() == Some(o))
            && self.node_id.is_none_or(|id| id == n.id)
    }
}
/// A statement tied to the owning connection. Iteration decodes one node at a
/// time and accounts candidate rows before applying reference-scan filters.
pub struct SnapshotScan<'a> {
    statement: rusqlite::Statement<'a>,
    params: Vec<Sql>,
    filter: NodeFilter,
    scanned: &'a Cell<u64>,
}
impl SnapshotScan<'_> {
    pub fn rows(&mut self) -> Result<impl Iterator<Item = Result<StoredNode>> + '_> {
        let filter = &self.filter;
        let scanned = self.scanned;
        Ok(self
            .statement
            .query_map(rusqlite::params_from_iter(&self.params), StoredNode::row)?
            .filter_map(move |row| match row {
                Ok(node) => {
                    scanned.set(scanned.get() + 1);
                    filter.matches(&node).then_some(Ok(node))
                }
                Err(e) => Some(Err(e.into())),
            }))
    }
}
#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct Collection {
    pub deferred: bool,
    pub snapshots: usize,
    pub units: usize,
}

pub struct StructuralStore {
    db: Connection,
    path: Option<PathBuf>,
    pub limit_bytes: Option<u64>,
    lease: Option<leases::Lease>,
    pub defer_busy_renewal: bool,
    staged: BTreeSet<i64>,
    scanned: Cell<u64>,
}
impl StructuralStore {
    pub fn open(path: Option<&Path>, cache_mb: Option<f64>) -> Result<Self> {
        if cache_mb.is_some_and(|v| !v.is_finite() || v < 0.) {
            return Err(StructuralError::Invalid(
                "cache_mb must be finite and nonnegative",
            ));
        }
        let path = path
            .filter(|_| cache_mb.is_none_or(|v| v >= 0.512))
            .map(Path::to_path_buf);
        if let Some(parent) = path
            .as_ref()
            .and_then(|p| p.parent())
            .filter(|p| !p.as_os_str().is_empty())
        {
            fs::create_dir_all(parent)?;
        }
        let mut db = Connection::open_with_flags(
            path.as_deref().unwrap_or(Path::new("")),
            OpenFlags::SQLITE_OPEN_READ_WRITE
                | OpenFlags::SQLITE_OPEN_CREATE
                | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        db.pragma_update(None, "foreign_keys", true)?;
        db.busy_timeout(Duration::from_secs(5))?;
        db.pragma_update(None, "cache_size", -65536)?;
        schema::validate(&db, true)?;
        if path.is_some() {
            db.pragma_update(None, "journal_mode", "WAL")?;
        }
        schema::migrate(&mut db, schema::manifest().version)?;
        let limit_bytes = if path.is_some() {
            cache_mb.map(|v| (v * 1_000_000.) as u64)
        } else {
            None
        };
        let lease = if path.is_some() {
            Some(leases::Lease::create(&db)?)
        } else {
            None
        };
        Ok(Self {
            db,
            path,
            limit_bytes,
            lease,
            defer_busy_renewal: false,
            staged: BTreeSet::new(),
            scanned: Cell::new(0),
        })
    }
    pub fn connection(&self) -> &Connection {
        &self.db
    }
    pub fn connection_mut(&mut self) -> &mut Connection {
        &mut self.db
    }
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }
    pub fn scanned(&self) -> u64 {
        self.scanned.get()
    }
    pub fn reset_scanned(&self) {
        self.scanned.set(0);
    }
    pub fn allocated_bytes(&self) -> Result<u64> {
        allocated(&self.db)
    }
    pub fn lease_id(&self) -> Option<&str> {
        self.lease.as_ref().map(|l| l.id.as_str())
    }
    pub fn renew(&self, force: bool) -> Result<()> {
        if let Some(lease) = &self.lease {
            lease.renew(&self.db, force, self.defer_busy_renewal)?;
        }
        Ok(())
    }
    pub fn current(&self) -> Result<Option<i64>> {
        current(&self.db)
    }
    pub fn find_unit(&mut self, key: &str) -> Result<Option<i64>> {
        self.renew(false)?;
        leases::unpin(&self.db, self.lease_id())?;
        let id: Option<i64> = self
            .db
            .query_row(
                "SELECT unit_id FROM k2_units WHERE unit_key=?1",
                [key],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(id) = id {
            self.staged.insert(id);
        }
        Ok(id)
    }
    pub fn load_unit(&self, unit: i64) -> Result<StructuralIr> {
        load_unit(&self.db, unit)
    }
    pub fn put_unit(
        &mut self,
        key: &str,
        ir: &StructuralIr,
        source_hash: &str,
        frontend_hash: &str,
        include_syntax: bool,
    ) -> Result<i64> {
        if ir.version != ken_program::IR_VERSION {
            return Err(StructuralError::Invalid("incompatible IR version"));
        }
        self.renew(false)?;
        let lease = self.lease_id().map(str::to_owned);
        let limit = self.limit_bytes;
        let unit = write(&mut self.db, limit, false, |db| {
            leases::unpin(db, lease.as_deref())?;
            let found: Option<i64> = db
                .query_row(
                    "SELECT unit_id FROM k2_units WHERE unit_key=?1",
                    [key],
                    |r| r.get(0),
                )
                .optional()?;
            if let Some(unit) = found {
                if include_syntax {
                    let old = load_unit(db, unit)?;
                    ast::ensure(db, unit, &old)?;
                }
                return Ok(unit);
            }
            let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
            serde_json::to_writer(&mut encoder, ir)?;
            let payload = encoder.finish()?;
            db.execute("INSERT INTO k2_units(unit_key,path,language,source_hash,frontend_hash,payload,coverage)VALUES(?1,?2,?3,?4,?5,?6,?7)",params![key,ir.path,ir.language,source_hash,frontend_hash,payload,ir.diagnostics.is_empty()])?;
            let unit = db.last_insert_rowid();
            projection::project(db, unit, ir)?;
            if include_syntax {
                ast::ensure(db, unit, ir)?;
            }
            Ok(unit)
        })?;
        self.staged.insert(unit);
        Ok(unit)
    }
    pub fn publish(
        &mut self,
        units: &[i64],
        expected_parent: Option<i64>,
        profile: &str,
        complete: bool,
    ) -> Result<i64> {
        if units.iter().copied().collect::<BTreeSet<_>>().len() != units.len() {
            return Err(StructuralError::Invalid("duplicate unit"));
        }
        let lease = self.lease_id().map(str::to_owned);
        let limit = self.limit_bytes;
        let snapshot = write(&mut self.db, limit, false, |db| {
            if current(db)? != expected_parent {
                return Err(StructuralError::Invalid("snapshot publication conflict"));
            }
            let mut members = Vec::new();
            let mut complete = complete;
            for &unit in units {
                let row: Option<(String, String, bool)> = db
                    .query_row(
                        "SELECT path,unit_key,coverage FROM k2_units WHERE unit_id=?1",
                        [unit],
                        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                    )
                    .optional()?;
                let (path, key, coverage) = row.ok_or(StructuralError::Missing(unit))?;
                complete &= coverage;
                members.push((path, key, unit));
            }
            members.sort();
            if members.iter().map(|m| &m.0).collect::<BTreeSet<_>>().len() != members.len() {
                return Err(StructuralError::Invalid(
                    "two revisions of one path in a snapshot",
                ));
            }
            let mut parts = vec![profile, if complete { "True" } else { "False" }];
            parts.extend(members.iter().map(|m| m.1.as_str()));
            let manifest = fingerprint(parts);
            let found: Option<i64> = db
                .query_row(
                    "SELECT snapshot_id FROM k2_snapshots WHERE manifest=?1",
                    [&manifest],
                    |r| r.get(0),
                )
                .optional()?;
            let snapshot = if let Some(id) = found {
                id
            } else {
                db.execute(
                    "INSERT INTO k2_snapshots(manifest,profile,coverage)VALUES(?1,?2,?3)",
                    params![manifest, profile, complete],
                )?;
                let id = db.last_insert_rowid();
                for (path, _, unit) in &members {
                    db.execute(
                        "INSERT INTO k2_snapshot_units VALUES(?1,?2,?3)",
                        params![id, unit, path],
                    )?;
                }
                id
            };
            db.execute("INSERT INTO k2_meta VALUES('published',?1)ON CONFLICT(key)DO UPDATE SET value=excluded.value",[snapshot.to_string()])?;
            leases::pin(db, lease.as_deref(), snapshot)?;
            Ok(snapshot)
        })?;
        if let Some(lease) = &mut self.lease {
            lease.renewed();
        }
        Ok(snapshot)
    }
    pub fn prepare_scan(&self, snapshot: i64, filter: NodeFilter) -> Result<SnapshotScan<'_>> {
        let exists: bool = self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM k2_snapshots WHERE snapshot_id=?1)",
            [snapshot],
            |r| r.get(0),
        )?;
        if !exists {
            return Err(StructuralError::Missing(snapshot));
        }
        let mut sql="SELECT n.node_id,n.unit_id,n.local_id,n.kind,n.name,n.owner,n.line,n.end_line,u.path,u.language FROM k2_nodes n JOIN k2_units u ON u.unit_id=n.unit_id JOIN k2_snapshot_units m ON m.unit_id=n.unit_id WHERE m.snapshot_id=?".to_string();
        let mut params = vec![Sql::Integer(snapshot)];
        if !filter.reference {
            if let Some(kind) = &filter.kind {
                sql.push_str(" AND n.kind=?");
                params.push(Sql::Text(kind.clone()));
            }
            if let Some(id) = filter.node_id {
                sql.push_str(" AND n.node_id=?");
                params.push(Sql::Integer(id));
            }
            if let Some((unit, owner)) = &filter.owner {
                sql.push_str(" AND n.unit_id=? AND n.owner=?");
                params.extend([Sql::Integer(*unit), Sql::Text(owner.clone())]);
            }
            if let Some(name) = &filter.name {
                let base = sql.clone();
                sql.push_str(" AND n.name=? UNION ALL ");
                sql.push_str(&base);
                sql.push_str(" AND n.name IS NULL");
                let base_params = params.clone();
                params.push(Sql::Text(name.clone()));
                params.extend(base_params);
            }
        }
        Ok(SnapshotScan {
            statement: self.db.prepare(&sql)?,
            params,
            filter,
            scanned: &self.scanned,
        })
    }
    pub fn properties(&self, node: &StoredNode) -> Result<BTreeMap<String, Scalar>> {
        let mut q = self
            .db
            .prepare("SELECT key,tag,value FROM k2_properties WHERE node_id=?1")?;
        let mut rows = q.query([node.id])?;
        let mut props = BTreeMap::new();
        while let Some(r) = rows.next()? {
            let key: String = r.get(0)?;
            let tag: String = r.get(1)?;
            props.insert(key, Scalar::decode(&tag, r.get_ref(2)?)?);
        }
        props.insert(
            "name".into(),
            node.name.clone().map_or(Scalar::Null, Scalar::String),
        );
        props.insert("path".into(), Scalar::String(node.path.clone()));
        props.insert("language".into(), Scalar::String(node.language.clone()));
        Ok(props)
    }
    pub fn program(&mut self, unit: i64) -> Result<Program> {
        let exists: bool = self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM k2_ast_units WHERE unit_id=?1 AND version=?2)",
            params![unit, ken_program::AST_VERSION],
            |r| r.get(0),
        )?;
        if !exists {
            let ir = self.load_unit(unit)?;
            let program = ken_program::normalize(&ir)?;
            match write(&mut self.db, self.limit_bytes, false, |db| {
                db.execute("DELETE FROM k2_ast_units WHERE unit_id=?1", [unit])?;
                ast::project(db, unit, &program)
            }) {
                Ok(()) => (),
                Err(StructuralError::Retention) => return Ok(program),
                Err(e) => return Err(e),
            }
        }
        ast::load(&self.db, unit)
    }
    pub fn operations(&mut self, unit: i64, owner: Option<&str>) -> Result<StructuralIr> {
        let exists: bool = self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM k2_operation_units WHERE unit_id=?1)",
            [unit],
            |r| r.get(0),
        )?;
        if !exists {
            let mut raw = self.load_unit(unit)?;
            match write(&mut self.db, self.limit_bytes, false, |db| {
                projection::project_operations(db, unit, &raw)
            }) {
                Ok(()) => (),
                Err(StructuralError::Retention) => {
                    raw.facts.clear();
                    raw.operations
                        .retain(|o| owner.is_none_or(|owner| o.owner == owner));
                    let spans = raw
                        .operations
                        .iter()
                        .map(|o| (o.start, o.end))
                        .collect::<BTreeSet<_>>();
                    raw.entities.retain(|(_, e)| {
                        ["CALL", "VALUE"].contains(&e.kind.as_str())
                            && e.attrs
                                .get("start_byte")
                                .and_then(|v| v.get().parse().ok())
                                .zip(e.attrs.get("end_byte").and_then(|v| v.get().parse().ok()))
                                .is_some_and(|span| spans.contains(&span))
                    });
                    return Ok(raw);
                }
                Err(e) => return Err(e),
            }
        }
        let row: Option<(String, String)> = self
            .db
            .query_row(
                "SELECT path,language FROM k2_units WHERE unit_id=?1",
                [unit],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let (path, language) = row.ok_or(StructuralError::Missing(unit))?;
        let mut ir = StructuralIr {
            path,
            language,
            entities: Vec::new(),
            operations: Vec::new(),
            facts: Vec::new(),
            capabilities: BTreeSet::new(),
            diagnostics: Vec::new(),
            version: ken_program::IR_VERSION.into(),
            relations: BTreeSet::new(),
            view: "source".into(),
        };
        let mut sql="SELECT local_id,owner,parent,kind,native_kind,role,start_byte,end_byte,line,attributes,entity_id FROM k2_operations WHERE unit_id=?".to_string();
        let mut args = vec![Sql::Integer(unit)];
        if let Some(owner) = owner {
            sql.push_str(" AND owner=?");
            args.push(Sql::Text(owner.into()));
        }
        sql.push_str(" ORDER BY start_byte,end_byte DESC,local_id");
        let mut q = self.db.prepare(&sql)?;
        let mut rows = q.query(rusqlite::params_from_iter(args))?;
        let mut entity_positions = BTreeMap::<String, usize>::new();
        while let Some(r) = rows.next()? {
            let id: String = r.get(0)?;
            let op_owner: String = r.get(1)?;
            let kind: String = r.get(3)?;
            let native: String = r.get(4)?;
            let start: i64 = r.get(6)?;
            let end: i64 = r.get(7)?;
            let line: i64 = r.get(8)?;
            let attrs: String = r.get(9)?;
            ir.operations.push(Operation {
                id,
                kind: kind.clone(),
                native_kind: native.clone(),
                parent: r.get(2)?,
                role: r.get(5)?,
                start,
                end,
                line,
                owner: op_owner.clone(),
                attrs: serde_json::from_str(&attrs)?,
            });
            if let Some(entity_id) = r.get::<_, Option<String>>(10)? {
                let attrs = attributes([
                    ("start_byte", serde_json::to_string(&start)?),
                    ("end_byte", serde_json::to_string(&end)?),
                    ("owner", serde_json::to_string(&op_owner)?),
                    ("native_kind", serde_json::to_string(&native)?),
                ])?;
                let entity = Entity {
                    id: entity_id.clone(),
                    kind: if kind == "CALL" { "CALL" } else { "VALUE" }.into(),
                    name: String::new(),
                    path: ir.path.clone(),
                    line,
                    end_line: line,
                    attrs,
                };
                if let Some(&position) = entity_positions.get(&entity_id) {
                    ir.entities[position].1 = entity;
                } else {
                    entity_positions.insert(entity_id.clone(), ir.entities.len());
                    ir.entities.push((entity_id, entity));
                }
            }
        }
        Ok(ir)
    }
    pub fn collect(&mut self, retain: usize, protected_units: &[i64]) -> Result<Collection> {
        if retain < 1 {
            return Err(StructuralError::Invalid(
                "retain must be at least one snapshot",
            ));
        }
        self.renew(true)?;
        let lease = self.lease_id().unwrap_or("").to_owned();
        let mut protected = self.staged.clone();
        protected.extend(protected_units.iter().copied());
        write(&mut self.db, self.limit_bytes, true, |db| {
            db.execute(
                "DELETE FROM k2_leases WHERE expires_ns<=?1",
                [leases::now()?],
            )?;
            let building: bool = db.query_row(
                "SELECT EXISTS(SELECT 1 FROM k2_leases WHERE snapshot_id IS NULL AND lease_id!=?1)",
                [&lease],
                |r| r.get(0),
            )?;
            if building {
                return Ok(Collection {
                    deferred: true,
                    snapshots: 0,
                    units: 0,
                });
            }
            let mut keep = db
                .prepare("SELECT snapshot_id FROM k2_snapshots ORDER BY snapshot_id DESC LIMIT ?1")?
                .query_map([retain as i64], |r| r.get::<_, i64>(0))?
                .collect::<rusqlite::Result<BTreeSet<_>>>()?;
            for id in db
                .prepare("SELECT snapshot_id FROM k2_leases WHERE snapshot_id IS NOT NULL")?
                .query_map([], |r| r.get::<_, i64>(0))?
            {
                keep.insert(id?);
            }
            if let Some(id) = current(db)? {
                keep.insert(id);
            }
            let all = db
                .prepare("SELECT snapshot_id FROM k2_snapshots")?
                .query_map([], |r| r.get::<_, i64>(0))?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            let mut snapshots = 0;
            for id in all {
                if !keep.contains(&id) {
                    snapshots +=
                        db.execute("DELETE FROM k2_snapshots WHERE snapshot_id=?1", [id])?;
                }
            }
            let unused=db.prepare("SELECT u.unit_id FROM k2_units u WHERE NOT EXISTS(SELECT 1 FROM k2_snapshot_units m WHERE m.unit_id=u.unit_id)")?.query_map([],|r|r.get::<_,i64>(0))?.collect::<rusqlite::Result<Vec<_>>>()?;
            let mut units = 0;
            for id in unused {
                if !protected.contains(&id) {
                    units += db.execute("DELETE FROM k2_units WHERE unit_id=?1", [id])?;
                }
            }
            Ok(Collection {
                deferred: false,
                snapshots,
                units,
            })
        })
    }
    pub fn pin_snapshot(&mut self, snapshot: i64) -> Result<()> {
        let lease = self.lease_id().map(str::to_owned);
        write(&mut self.db, None, true, |db| {
            let exists: bool = db.query_row(
                "SELECT EXISTS(SELECT 1 FROM k2_snapshots WHERE snapshot_id=?1)",
                [snapshot],
                |r| r.get(0),
            )?;
            if !exists {
                return Err(StructuralError::Missing(snapshot));
            }
            leases::pin(db, lease.as_deref(), snapshot)
        })?;
        if let Some(lease) = &mut self.lease {
            lease.renewed();
        }
        Ok(())
    }
    pub fn close(mut self) -> Result<()> {
        self.remove_lease()
    }
    fn remove_lease(&mut self) -> Result<()> {
        if let Some(lease) = self.lease.take() {
            let v: i64 = self.db.query_row("PRAGMA user_version", [], |r| r.get(0))?;
            if v >= 3 {
                self.db
                    .execute("DELETE FROM k2_leases WHERE lease_id=?1", [lease.id])?;
            }
        }
        Ok(())
    }
}
impl Drop for StructuralStore {
    fn drop(&mut self) {
        let _ = self.remove_lease();
    }
}
fn current(db: &Connection) -> Result<Option<i64>> {
    let v: Option<String> = db
        .query_row("SELECT value FROM k2_meta WHERE key='published'", [], |r| {
            r.get(0)
        })
        .optional()?;
    v.map(|s| {
        s.parse()
            .map_err(|_| StructuralError::Invalid("invalid published snapshot identity"))
    })
    .transpose()
}
fn load_unit(db: &Connection, unit: i64) -> Result<StructuralIr> {
    let bytes: Vec<u8> = db
        .query_row(
            "SELECT payload FROM k2_units WHERE unit_id=?1",
            [unit],
            |r| r.get(0),
        )
        .optional()?
        .ok_or(StructuralError::Missing(unit))?;
    let mut text = String::new();
    ZlibDecoder::new(&bytes[..]).read_to_string(&mut text)?;
    Ok(StructuralIr::from_json(&text)?)
}
fn allocated(db: &Connection) -> Result<u64> {
    let pages: i64 = db.query_row("PRAGMA page_count", [], |r| r.get(0))?;
    let size: i64 = db.query_row("PRAGMA page_size", [], |r| r.get(0))?;
    pages
        .checked_mul(size)
        .and_then(|n| u64::try_from(n).ok())
        .ok_or(StructuralError::Invalid("invalid allocated byte count"))
}
fn write<T>(
    db: &mut Connection,
    limit: Option<u64>,
    reclamation: bool,
    body: impl FnOnce(&Connection) -> Result<T>,
) -> Result<T> {
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let result = body(&tx)?;
    if !reclamation
        && let Some(cap) = limit
        && allocated(&tx)? > cap
    {
        return Err(StructuralError::Retention);
    }
    tx.commit()?;
    Ok(result)
}
fn fingerprint<'a>(parts: impl IntoIterator<Item = &'a str>) -> String {
    let mut hash = Sha256::new();
    for part in parts {
        let bytes = part.as_bytes();
        hash.update((bytes.len() as u64).to_be_bytes());
        hash.update(bytes);
    }
    format!("{hash:x}", hash = hash.finalize())
}
fn attributes<const N: usize>(values: [(&str, String); N]) -> Result<Attributes> {
    values
        .into_iter()
        .map(|(key, v)| Ok((key.into(), serde_json::value::RawValue::from_string(v)?)))
        .collect()
}
