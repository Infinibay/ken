use crate::{StoreError, StoreResult, WriteTransaction, error::sql_error};
use rusqlite::{Connection, OptionalExtension, params};
use std::{fmt, str::FromStr};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum VectorSpace {
    Files,
    Symbols,
    IntentSources,
}

impl VectorSpace {
    pub const ALL: [Self; 3] = [Self::Files, Self::Symbols, Self::IntentSources];
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Files => "ci_files",
            Self::Symbols => "ci_symbols",
            Self::IntentSources => "ci_intent_sources",
        }
    }
}

impl fmt::Display for VectorSpace {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for VectorSpace {
    type Err = StoreError;
    fn from_str(value: &str) -> StoreResult<Self> {
        Self::ALL
            .into_iter()
            .find(|s| s.as_str() == value)
            .ok_or_else(|| StoreError::UnknownSpace(value.into()))
    }
}

pub fn high_water(conn: &Connection, space: VectorSpace) -> StoreResult<i64> {
    let value = conn
        .query_row(
            "SELECT next_slot FROM ci_vec_alloc WHERE space=?1",
            [space.as_str()],
            |r| r.get::<_, i64>(0),
        )
        .optional()
        .map_err(|e| sql_error(conn, e))?
        .unwrap_or(0);
    if value < 0 {
        return Err(StoreError::InvalidSlot("negative high-water mark"));
    }
    Ok(value)
}

pub fn allocate(
    tx: &mut WriteTransaction<'_>,
    space: VectorSpace,
    count: usize,
) -> StoreResult<Vec<i64>> {
    if count == 0 {
        return Ok(Vec::new());
    }
    let requested = i64::try_from(count)
        .map_err(|_| StoreError::InvalidSlot("count exceeds SQLite integer range"))?;
    let conn = active(tx)?;
    let start = high_water(conn, space)?;
    let table = space.as_str();
    let mut statement = conn
        .prepare(&format!("SELECT free.slot, EXISTS(SELECT 1 FROM {table} AS owner WHERE owner.vec_slot=free.slot) FROM ci_vec_free AS free WHERE free.space=?1 ORDER BY free.slot LIMIT ?2"))
        .map_err(|e| sql_error(conn, e))?;
    let rows = statement
        .query_map(params![space.as_str(), requested], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, bool>(1)?))
        })
        .map_err(|e| sql_error(conn, e))?;
    let mut reused = Vec::new();
    for row in rows {
        let (slot, owned) = row.map_err(|e| sql_error(conn, e))?;
        if owned {
            return Err(StoreError::InvalidSlot(
                "free slot is still referenced by an index row",
            ));
        }
        if slot < 0 || slot >= start {
            return Err(StoreError::InvalidSlot("free slot outside allocated range"));
        }
        reused
            .try_reserve(1)
            .map_err(|_| StoreError::InvalidSlot("free-list exceeds available capacity"))?;
        reused.push(slot);
    }
    let remaining = count
        .checked_sub(reused.len())
        .ok_or(StoreError::InvalidSlot("free-list count exceeds request"))?;
    let remaining = i64::try_from(remaining)
        .map_err(|_| StoreError::InvalidSlot("count exceeds SQLite integer range"))?;
    let end = start
        .checked_add(remaining)
        .ok_or(StoreError::InvalidSlot("high-water mark overflow"))?;
    let mut result = Vec::new();
    result
        .try_reserve_exact(count)
        .map_err(|_| StoreError::InvalidSlot("requested slots exceed available capacity"))?;
    result.extend(reused.iter().copied());
    result.extend(start..end);
    for slot in reused {
        conn.execute(
            "DELETE FROM ci_vec_free WHERE space=?1 AND slot=?2",
            params![space.as_str(), slot],
        )
        .map_err(|e| sql_error(conn, e))?;
    }
    if remaining > 0 {
        conn.execute("INSERT INTO ci_vec_alloc(space,next_slot) VALUES(?1,?2) ON CONFLICT(space) DO UPDATE SET next_slot=excluded.next_slot",
            params![space.as_str(),end]).map_err(|e|sql_error(conn,e))?;
    }
    Ok(result)
}

pub fn release(
    tx: &mut WriteTransaction<'_>,
    space: VectorSpace,
    slots: &[i64],
) -> StoreResult<()> {
    if slots.is_empty() {
        return Ok(());
    }
    if slots.iter().any(|&slot| slot < 0) {
        return Err(StoreError::InvalidSlot("negative released slot"));
    }
    let conn = active(tx)?;
    let mut statement = conn
        .prepare("INSERT OR IGNORE INTO ci_vec_free(space,slot) VALUES(?1,?2)")
        .map_err(|e| sql_error(conn, e))?;
    for slot in slots {
        statement
            .execute(params![space.as_str(), slot])
            .map_err(|e| sql_error(conn, e))?;
    }
    Ok(())
}

fn active<'a>(tx: &'a WriteTransaction<'_>) -> StoreResult<&'a Connection> {
    if tx.connection().is_autocommit() {
        return Err(StoreError::InvalidSlot("write transaction already ended"));
    }
    Ok(tx.connection())
}
