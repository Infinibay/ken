//! Three legacy vector spaces; SQLite owns allocation and rollback boundaries.
use crate::{DocumentTarget, PreparedFile, Result};
use ken_store::{VectorSpace, VectorStore, WriteTransaction, allocate, release};
use rusqlite::params;
use std::{collections::BTreeMap, path::Path};
pub struct LegacyStores {
    by_space: BTreeMap<VectorSpace, VectorStore>,
}
impl LegacyStores {
    pub fn open(directory: &Path, dim: usize, model: Option<&str>) -> Result<Self> {
        let mut by_space = BTreeMap::new();
        for space in VectorSpace::ALL {
            by_space.insert(space, VectorStore::open(directory, space, dim, model)?);
        }
        Ok(Self { by_space })
    }
    pub fn get(&self, space: VectorSpace) -> &VectorStore {
        self.by_space
            .get(&space)
            .expect("all three spaces opened together")
    }
    pub fn flush(&self) -> Result<()> {
        for store in self.by_space.values() {
            store.flush()?;
        }
        Ok(())
    }
}
pub(crate) fn blob(
    file: &PreparedFile,
    target: &DocumentTarget,
    stores: Option<&LegacyStores>,
) -> Option<Vec<u8>> {
    if stores.is_some() {
        None
    } else {
        file.vectors
            .get(target)
            .map(|v| v.iter().flat_map(|n| n.to_le_bytes()).collect())
    }
}
pub(crate) fn file_vector(
    tx: &mut WriteTransaction<'_>,
    stores: Option<&LegacyStores>,
    file_id: i64,
    file: &PreparedFile,
) -> Result<()> {
    let previous: Option<i64> = tx.connection().query_row(
        "SELECT vec_slot FROM ci_files WHERE id=?1",
        [file_id],
        |r| r.get(0),
    )?;
    let replacement = stores.zip(file.vectors.get(&DocumentTarget::File));
    let Some((stores, vector)) = replacement else {
        tx.connection()
            .execute("UPDATE ci_files SET vec_slot=NULL WHERE id=?1", [file_id])?;
        if let Some(previous) = previous {
            release(tx, VectorSpace::Files, &[previous])?;
        }
        return Ok(());
    };
    let slot = allocate(tx, VectorSpace::Files, 1)?[0];
    stores
        .get(VectorSpace::Files)
        .write(&[slot], std::slice::from_ref(vector), false)?;
    tx.connection().execute(
        "UPDATE ci_files SET vec_slot=?1 WHERE id=?2",
        params![slot, file_id],
    )?;
    if let Some(previous) = previous {
        release(tx, VectorSpace::Files, &[previous])?;
    }
    Ok(())
}
pub(crate) fn vectors(
    tx: &mut WriteTransaction<'_>,
    stores: Option<&LegacyStores>,
    space: VectorSpace,
    vectors: &[Option<&[f32]>],
) -> Result<Vec<Option<i64>>> {
    let mut result = vec![None; vectors.len()];
    let Some(stores) = stores else {
        return Ok(result);
    };
    let present: Vec<_> = vectors
        .iter()
        .enumerate()
        .filter_map(|(i, v)| v.map(|v| (i, v.to_vec())))
        .collect();
    if present.is_empty() {
        return Ok(result);
    }
    let slots = allocate(tx, space, present.len())?;
    let values: Vec<_> = present.iter().map(|(_, v)| v.clone()).collect();
    stores.get(space).write(&slots, &values, false)?;
    for (slot, (i, _)) in slots.into_iter().zip(present) {
        result[i] = Some(slot)
    }
    Ok(result)
}
