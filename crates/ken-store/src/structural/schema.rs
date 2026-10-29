use super::{Result, StructuralError};
use rusqlite::{Connection, TransactionBehavior};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, sync::OnceLock};
#[derive(Deserialize)]
pub(super) struct Migration {
    pub version: i64,
    pub up: Vec<String>,
    pub down: Vec<String>,
    pub checksum: String,
    pub tables: Vec<String>,
}
#[derive(Deserialize)]
pub(super) struct Layouts {
    pub nodes: [String; 3],
    pub scopes: [String; 3],
    pub symbols: [String; 3],
    pub references: [String; 3],
}
impl Layouts {
    pub fn families(&self) -> [(&str, &[String; 3]); 4] {
        [
            ("nodes", &self.nodes),
            ("scopes", &self.scopes),
            ("symbols", &self.symbols),
            ("references", &self.references),
        ]
    }
}
#[derive(Deserialize)]
pub(super) struct Schema {
    pub format: String,
    pub application_id: i64,
    pub version: i64,
    pub migrations: Vec<Migration>,
    pub layouts: Layouts,
    pub identities: std::collections::BTreeMap<String, String>,
}
pub(super) fn manifest() -> &'static Schema {
    static SCHEMA: OnceLock<Schema> = OnceLock::new();
    SCHEMA.get_or_init(|| {
        let s: Schema =
            serde_json::from_str(include_str!("../../resources/structural-schema.json"))
                .expect("embedded structural migration data");
        assert_eq!(s.format, "ken-structural-schema/1");
        for (i, m) in s.migrations.iter().enumerate() {
            assert_eq!(m.version, i as i64 + 1);
            assert_eq!(
                format!("{:x}", Sha256::digest(m.up.join("\n").as_bytes())),
                m.checksum
            );
        }
        s
    })
}
pub(super) fn ddl(db: &Connection) -> rusqlite::Result<Vec<(String, String, Option<String>)>> {
    db.prepare(
        "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name",
    )?
    .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
    .collect()
}
pub fn validate(db: &Connection, allow_empty: bool) -> Result<i64> {
    let schema = manifest();
    let app: i64 = db.query_row("PRAGMA application_id", [], |r| r.get(0))?;
    let version: i64 = db.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    let tables = db
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")?
        .query_map([], |r| r.get::<_, String>(0))?
        .collect::<rusqlite::Result<BTreeSet<_>>>()?;
    if tables.is_empty()
        && (app == 0 || app == schema.application_id)
        && version == 0
        && allow_empty
        && ddl(db)?.is_empty()
    {
        return Ok(0);
    }
    if app != schema.application_id
        || version < 1
        || version > schema.version
        || tables
            != schema.migrations[(version - 1) as usize]
                .tables
                .iter()
                .cloned()
                .collect()
    {
        return Err(StructuralError::Format(
            "unrecognized structural store ownership or schema; no changes made",
        ));
    }
    let ledger = db
        .prepare("SELECT version,checksum FROM k2_migrations ORDER BY version")?
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let expected = schema.migrations[..version as usize]
        .iter()
        .map(|m| (m.version, m.checksum.clone()))
        .collect::<Vec<_>>();
    if ledger != expected {
        return Err(StructuralError::Format("migration checksum mismatch"));
    }
    let clean = Connection::open_in_memory()?;
    for m in &schema.migrations[..version as usize] {
        for sql in &m.up {
            clean.execute_batch(sql)?;
        }
    }
    if ddl(db)? != ddl(&clean)? {
        return Err(StructuralError::Format(
            "schema differs from the migration manifest",
        ));
    }
    Ok(version)
}
pub fn migrate(db: &mut Connection, target: i64) -> Result<()> {
    let schema = manifest();
    if !(0..=schema.version).contains(&target) {
        return Err(StructuralError::Format("unsupported migration target"));
    }
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let current = validate(&tx, true)?;
    if current < target {
        for step in current + 1..=target {
            let m = &schema.migrations[(step - 1) as usize];
            for sql in &m.up {
                tx.execute_batch(sql)?;
            }
            tx.execute(
                "INSERT INTO k2_migrations VALUES(?1,?2)",
                rusqlite::params![step, m.checksum],
            )?;
            tx.pragma_update(None, "application_id", schema.application_id)?;
            tx.pragma_update(None, "user_version", step)?;
        }
    } else {
        for step in (target + 1..=current).rev() {
            for sql in &schema.migrations[(step - 1) as usize].down {
                tx.execute_batch(sql)?;
            }
            if step > 1 {
                tx.execute("DELETE FROM k2_migrations WHERE version=?1", [step])?;
            }
            tx.pragma_update(None, "user_version", step - 1)?;
        }
    }
    tx.commit()?;
    Ok(())
}
