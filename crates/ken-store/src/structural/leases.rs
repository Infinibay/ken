use super::{Result, StructuralError};
use rusqlite::{Connection, OptionalExtension, params};
use std::cell::Cell;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
const TTL: i64 = 300_000_000_000;
pub(super) fn now() -> Result<i64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| StructuralError::Invalid("clock before Unix epoch"))?
        .as_nanos()
        .try_into()
        .map_err(|_| StructuralError::Invalid("lease clock outside SQLite range"))
}
pub(super) struct Lease {
    pub id: String,
    next: Cell<Instant>,
}
impl Lease {
    pub fn create(db: &Connection) -> Result<Self> {
        let mut bytes: Vec<u8> = db.query_row("SELECT randomblob(16)", [], |r| r.get(0))?;
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        let id = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
        db.execute(
            "INSERT INTO k2_leases VALUES(?1,NULL,?2)",
            params![id, now()? + TTL],
        )?;
        Ok(Self {
            id,
            next: Cell::new(Instant::now() + Duration::from_secs(15)),
        })
    }
    pub fn renewed(&self) {
        self.next.set(Instant::now() + Duration::from_secs(15));
    }
    pub fn renew(&self, db: &Connection, force: bool, defer_busy: bool) -> Result<()> {
        if !force && Instant::now() < self.next.get() {
            return Ok(());
        }
        match renew(db, &self.id) {
            Ok(()) => self.renewed(),
            Err(StructuralError::Sql(e))
                if !force
                    && defer_busy
                    && e.sqlite_error_code() == Some(rusqlite::ErrorCode::DatabaseBusy) =>
            {
                let current = now()?;
                let expires: Option<i64> = db
                    .query_row(
                        "SELECT expires_ns FROM k2_leases WHERE lease_id=?1 AND expires_ns>?2",
                        params![self.id, current],
                        |r| r.get(0),
                    )
                    .optional()?;
                let current = now()?;
                if expires.is_none_or(|e| e <= current) {
                    return Err(StructuralError::Expired);
                }
                self.next.set(
                    Instant::now()
                        + Duration::from_nanos(
                            (expires.unwrap() - current).min(1_000_000_000) as u64
                        ),
                );
            }
            Err(e) => return Err(e),
        }
        Ok(())
    }
}
pub(super) fn renew(db: &Connection, id: &str) -> Result<()> {
    let current = now()?;
    let n = db.execute(
        "UPDATE k2_leases SET expires_ns=?1 WHERE lease_id=?2 AND expires_ns>?3",
        params![current + TTL, id, current],
    )?;
    if n != 1 {
        return Err(StructuralError::Expired);
    }
    Ok(())
}
pub(super) fn unpin(db: &Connection, id: Option<&str>) -> Result<()> {
    if let Some(id) = id {
        db.execute(
            "UPDATE k2_leases SET snapshot_id=NULL WHERE lease_id=?1 AND snapshot_id IS NOT NULL",
            [id],
        )?;
    }
    Ok(())
}
pub(super) fn pin(db: &Connection, id: Option<&str>, snapshot: i64) -> Result<()> {
    if let Some(id) = id {
        renew(db, id)?;
        db.execute(
            "UPDATE k2_leases SET snapshot_id=?1 WHERE lease_id=?2",
            params![snapshot, id],
        )?;
    }
    Ok(())
}
