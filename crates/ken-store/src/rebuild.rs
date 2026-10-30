//! Stage a complete replacement without invalidating live pointers while encoding.
use crate::{
    MaintenanceEvent, ProjectStore, StoreError, StoreResult, VectorSpace, VectorStore,
    WriteTransaction, error::sql_error, high_water, recovery,
};
use rusqlite::{Connection, types::ValueRef};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
};
struct SpaceState {
    rows: BTreeMap<i64, Option<i64>>,
    required: BTreeSet<i64>,
    high_water: i64,
}
struct Snapshot {
    digest: [u8; 32],
    spaces: BTreeMap<VectorSpace, SpaceState>,
}
fn field(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
}
fn snapshot(conn: &Connection) -> StoreResult<Snapshot> {
    let mut hash = Sha256::new();
    let mut spaces = BTreeMap::new();
    for space in VectorSpace::ALL {
        field(&mut hash, space.as_str().as_bytes());
        let high_water = high_water(conn, space)?;
        hash.update(high_water.to_le_bytes());
        let mut statement = conn
            .prepare("SELECT slot FROM ci_vec_free WHERE space=? ORDER BY slot")
            .map_err(|e| sql_error(conn, e))?;
        let free = statement
            .query_map([space.as_str()], |r| r.get::<_, i64>(0))
            .map_err(|e| sql_error(conn, e))?
            .collect::<rusqlite::Result<BTreeSet<_>>>()
            .map_err(|e| sql_error(conn, e))?;
        for slot in &free {
            if *slot < 0 || *slot >= high_water {
                return Err(StoreError::InvalidSlot("free slot outside high-water mark"));
            }
            hash.update(slot.to_le_bytes());
        }
        field(&mut hash, b"rows");
        let mut rows = BTreeMap::new();
        let mut required = BTreeSet::new();
        let mut owners = BTreeSet::new();
        let mut statement = conn
            .prepare(&format!(
                "SELECT id,vec_slot,embedding FROM {space} ORDER BY id"
            ))
            .map_err(|e| sql_error(conn, e))?;
        let mut cursor = statement.query([]).map_err(|e| sql_error(conn, e))?;
        while let Some(row) = cursor.next().map_err(|e| sql_error(conn, e))? {
            let id: i64 = row.get(0).map_err(|e| sql_error(conn, e))?;
            let slot: Option<i64> = row.get(1).map_err(|e| sql_error(conn, e))?;
            hash.update(id.to_le_bytes());
            hash.update([u8::from(slot.is_some())]);
            if let Some(slot) = slot {
                if slot < 0 || slot >= high_water || free.contains(&slot) || !owners.insert(slot) {
                    return Err(StoreError::InvalidSlot(
                        "inconsistent live vector ownership",
                    ));
                }
                hash.update(slot.to_le_bytes());
            }
            match row.get_ref(2).map_err(|e| sql_error(conn, e))? {
                ValueRef::Null => {
                    hash.update([0]);
                    if slot.is_some() {
                        required.insert(id);
                    }
                }
                ValueRef::Blob(raw) => {
                    hash.update([1]);
                    field(&mut hash, raw);
                    required.insert(id);
                }
                _ => {
                    return Err(StoreError::InvalidSlot(
                        "inline embedding must be a blob or NULL",
                    ));
                }
            }
            rows.insert(id, slot);
        }
        spaces.insert(
            space,
            SpaceState {
                rows,
                required,
                high_water,
            },
        );
    }
    Ok(Snapshot {
        digest: hash.finalize().into(),
        spaces,
    })
}
pub struct VectorRebuild {
    database: String,
    live: PathBuf,
    staging: Option<tempfile::TempDir>,
    dim: usize,
    initial: Snapshot,
    stores: BTreeMap<VectorSpace, VectorStore>,
    written: BTreeMap<VectorSpace, BTreeMap<i64, i64>>,
    next: BTreeMap<VectorSpace, i64>,
}
impl VectorRebuild {
    pub fn begin(project: &ProjectStore, dim: usize, model: Option<&str>) -> StoreResult<Self> {
        let live = project.vector_directory();
        let parent = live
            .parent()
            .ok_or(StoreError::InvalidSlot("vector directory has no parent"))?;
        let staging = tempfile::Builder::new()
            .prefix(".vectors-stage-")
            .tempdir_in(parent)
            .map_err(|e| StoreError::io(parent, e))?;
        let conn = project.database().connection();
        let read = conn
            .unchecked_transaction()
            .map_err(|e| sql_error(conn, e))?;
        let initial = snapshot(&read)?;
        read.commit().map_err(|e| sql_error(conn, e))?;
        let mut stores = BTreeMap::new();
        let mut written = BTreeMap::new();
        let mut next = BTreeMap::new();
        for space in VectorSpace::ALL {
            stores.insert(space, VectorStore::open(staging.path(), space, dim, model)?);
            written.insert(space, BTreeMap::new());
            next.insert(space, initial.spaces[&space].high_water);
        }
        Ok(Self {
            database: conn.path().unwrap_or("").into(),
            live,
            staging: Some(staging),
            dim,
            initial,
            stores,
            written,
            next,
        })
    }
    pub fn write(
        &mut self,
        space: VectorSpace,
        ids: &[i64],
        vectors: &[Vec<f32>],
    ) -> StoreResult<()> {
        if ids.len() != vectors.len() {
            return Err(StoreError::Dimension("row/vector counts differ"));
        }
        let state = &self.initial.spaces[&space];
        let mut unique = BTreeSet::new();
        let mut slots = Vec::with_capacity(ids.len());
        for id in ids {
            if !unique.insert(*id) || self.written[&space].contains_key(id) {
                return Err(StoreError::InvalidSlot("duplicate replacement row"));
            }
            let slot = state
                .rows
                .get(id)
                .ok_or(StoreError::InvalidSlot("replacement row was not captured"))?;
            let slot = match slot {
                Some(slot) => *slot,
                None => {
                    let next = self.next.get_mut(&space).expect("all spaces");
                    let slot = *next;
                    *next = next
                        .checked_add(1)
                        .ok_or(StoreError::InvalidSlot("replacement allocation overflow"))?;
                    slot
                }
            };
            slots.push(slot);
        }
        self.stores[&space].write(&slots, vectors, false)?;
        self.written
            .get_mut(&space)
            .expect("all spaces")
            .extend(ids.iter().copied().zip(slots));
        Ok(())
    }
    pub fn commit(
        mut self,
        project: &mut ProjectStore,
        finalize: impl FnOnce(&WriteTransaction<'_>) -> StoreResult<()>,
        progress: &mut impl FnMut(MaintenanceEvent),
    ) -> StoreResult<()> {
        if project.database().connection().path().unwrap_or("") != self.database
            || project.vector_directory() != self.live
        {
            return Err(StoreError::InvalidSlot(
                "replacement belongs to a different project",
            ));
        }
        for space in VectorSpace::ALL {
            if !self.initial.spaces[&space]
                .required
                .iter()
                .all(|id| self.written[&space].contains_key(id))
            {
                return Err(StoreError::InvalidSlot(
                    "replacement omitted live vector rows",
                ));
            }
            self.stores[&space].flush()?;
        }
        self.stores.clear();
        let result = (|| {
            let tx = project.database_mut().immediate()?;
            let conn = tx.connection();
            if snapshot(conn)?.digest != self.initial.digest {
                return Err(StoreError::InvalidSlot(
                    "vector ownership changed while reencoding",
                ));
            }
            for space in VectorSpace::ALL {
                for (id, slot) in &self.written[&space] {
                    conn.execute(
                        &format!("UPDATE {space} SET vec_slot=?1,embedding=NULL WHERE id=?2"),
                        rusqlite::params![slot, id],
                    )
                    .map_err(|e| sql_error(conn, e))?;
                }
                conn.execute("INSERT INTO ci_vec_alloc(space,next_slot)VALUES(?1,?2)ON CONFLICT(space)DO UPDATE SET next_slot=excluded.next_slot",rusqlite::params![space.as_str(),self.next[&space]]).map_err(|e|sql_error(conn,e))?;
            }
            finalize(&tx)?;
            let staging = self.staging.take().expect("unpublished staging");
            crate::maintenance::copy_unmanaged(&self.live, staging.path())?;
            let mut publication =
                recovery::Publication::prepare_rebuild(&self.live, staging, self.dim)?;
            publication.publish(progress)?;
            crate::database::set_meta(conn, recovery::MARKER, publication.id())
                .map_err(|e| sql_error(conn, e))?;
            tx.commit()?;
            progress(MaintenanceEvent::DatabaseCommitted);
            Ok(())
        })();
        // On ordinary error recover now; on process interruption/panic ProjectStore::open recovers.
        recovery::recover(project.database_mut(), &self.live)?;
        if result.is_ok() {
            progress(MaintenanceEvent::Cleaned);
        }
        result
    }
}
