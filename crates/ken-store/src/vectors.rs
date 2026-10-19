use crate::{
    StoreError, StoreResult, VectorManifest, VectorSpace,
    error::sql_error,
    high_water,
    segments::{DirtySegments, Segments},
};
use rusqlite::Connection;
use serde::Serialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

/// Physical vector values for one validated space; allocation/row ownership stays in SQLite.
pub struct VectorStore {
    manifest: VectorManifest,
    segments: Segments,
    dirty: DirtySegments,
}

fn normalize(vector: &[f32]) -> StoreResult<Vec<f32>> {
    if vector.iter().any(|n| !n.is_finite()) {
        return Err(StoreError::NonFinite);
    }
    let norm = vector.iter().fold(0.0f32, |total, n| total + n * n).sqrt();
    if !norm.is_finite() {
        return Err(StoreError::NonFinite);
    }
    let floor = norm.max(1e-12);
    Ok(vector.iter().map(|n| n / floor).collect())
}

impl VectorStore {
    pub fn open(
        directory: &Path,
        space: VectorSpace,
        dim: usize,
        model: Option<&str>,
    ) -> StoreResult<Self> {
        let manifest = VectorManifest::open(directory, space, dim, model)?;
        let segments = Segments {
            directory: directory.into(),
            space,
            capacity: manifest.segment_bytes()?,
        };
        Ok(Self {
            manifest,
            segments,
            dirty: DirtySegments::default(),
        })
    }
    pub fn manifest(&self) -> &VectorManifest {
        &self.manifest
    }
    pub fn space(&self) -> VectorSpace {
        self.segments.space
    }
    fn location(&self, slot: i64) -> StoreResult<(u64, u64)> {
        let slot =
            u64::try_from(slot).map_err(|_| StoreError::InvalidSlot("negative vector slot"))?;
        let row = self.manifest.row_bytes()? as u64;
        slot.checked_add(1)
            .and_then(|n| n.checked_mul(row))
            .filter(|n| *n <= i64::MAX as u64)
            .ok_or(StoreError::InvalidSlot("vector offset exceeds file range"))?;
        let capacity = self.manifest.segment_rows as u64;
        Ok((slot / capacity, (slot % capacity) * row))
    }
    pub fn write(&self, slots: &[i64], vectors: &[Vec<f32>], durable: bool) -> StoreResult<()> {
        if slots.is_empty() {
            return Ok(());
        }
        if slots.len() != vectors.len() {
            return Err(StoreError::Dimension("slot and vector counts differ"));
        }
        let mut batches: BTreeMap<u64, Vec<(u64, Vec<u8>)>> = BTreeMap::new();
        // Validate and normalize the entire input before creating or changing a segment.
        for (&slot, vector) in slots.iter().zip(vectors) {
            if vector.len() != self.manifest.dim {
                return Err(StoreError::Dimension(
                    "vector dimension differs from manifest",
                ));
            }
            let (segment, offset) = self.location(slot)?;
            let bytes = normalize(vector)?
                .iter()
                .flat_map(|n| n.to_le_bytes())
                .collect();
            batches.entry(segment).or_default().push((offset, bytes));
        }
        // Preflight existing files before writing any row. I/O errors remain errors.
        for &index in batches.keys() {
            self.segments.open(index, false)?;
        }
        for (index, entries) in batches {
            let file = self
                .segments
                .open(index, true)?
                .ok_or(StoreError::InvalidSlot("created segment unavailable"))?;
            self.dirty.during_write(index, || {
                for (offset, bytes) in entries {
                    self.segments.write(index, &file, offset, &bytes)?;
                }
                StoreResult::Ok(())
            })?;
            if durable {
                file.sync_all()
                    .map_err(|e| StoreError::io(&self.segments.path(index), e))?;
            }
        }
        Ok(())
    }
    pub fn read(&self, slots: &[i64]) -> StoreResult<Vec<Vec<f32>>> {
        let locations = slots
            .iter()
            .map(|&slot| self.location(slot))
            .collect::<StoreResult<Vec<_>>>()?;
        let mut rows = Vec::with_capacity(slots.len());
        let mut bytes = vec![0; self.manifest.row_bytes()?];
        for (index, offset) in locations {
            if let Some(file) = self.segments.open(index, false)? {
                self.segments.read(index, &file, offset, &mut bytes)?;
                rows.push(decode(&bytes));
            } else {
                rows.push(vec![0.; self.manifest.dim]);
            }
        }
        Ok(rows)
    }
    pub fn scores(&self, query: &[f32], count: usize) -> StoreResult<Vec<f32>> {
        if count == 0 {
            return Ok(Vec::new());
        }
        if query.len() != self.manifest.dim {
            return Err(StoreError::Dimension(
                "query dimension differs from manifest",
            ));
        }
        let last = i64::try_from(count - 1)
            .map_err(|_| StoreError::InvalidSlot("score count exceeds slot range"))?;
        self.location(last)?;
        let query = normalize(query)?;
        let mut output = Vec::new();
        output
            .try_reserve_exact(count)
            .map_err(|_| StoreError::InvalidSlot("score allocation exceeds available memory"))?;
        output.resize(count, 0.);
        let row_bytes = self.manifest.row_bytes()?;
        let block_rows = (8 * 1024 * 1024 / row_bytes)
            .max(1)
            .min(self.manifest.segment_rows);
        let mut buffer = vec![0u8; block_rows * row_bytes];
        for base in (0..count).step_by(self.manifest.segment_rows) {
            let index = (base / self.manifest.segment_rows) as u64;
            let Some(file) = self.segments.open(index, false)? else {
                continue;
            };
            let rows = (count - base).min(self.manifest.segment_rows);
            for lo in (0..rows).step_by(block_rows) {
                let end = (lo + block_rows).min(rows);
                let bytes = &mut buffer[..(end - lo) * row_bytes];
                self.segments
                    .read(index, &file, (lo * row_bytes) as u64, bytes)?;
                for (target, row) in output[base + lo..base + end]
                    .iter_mut()
                    .zip(bytes.chunks_exact(row_bytes))
                {
                    *target = row.chunks_exact(4).zip(&query).fold(0f32, |sum, (n, q)| {
                        sum + f32::from_le_bytes([n[0], n[1], n[2], n[3]]) * q
                    });
                }
            }
        }
        Ok(output)
    }
    pub fn flush(&self) -> StoreResult<()> {
        let dirty = self.dirty.take();
        for &index in &dirty {
            if let Err(error) = self.segments.sync(index) {
                self.dirty.restore(dirty);
                return Err(error);
            }
        }
        Ok(())
    }
    pub fn bytes_on_disk(&self) -> StoreResult<u64> {
        self.segments.bytes_on_disk()
    }
}

fn decode(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(4)
        .map(|n| f32::from_le_bytes([n[0], n[1], n[2], n[3]]))
        .collect()
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct VerificationReport {
    pub high_water: i64,
    pub referenced: usize,
    pub free: usize,
    pub leaked: i64,
    pub out_of_range: usize,
    pub double_booked: usize,
    pub segments: usize,
}
#[derive(Debug, PartialEq)]
pub struct LiveScores {
    pub slots: Vec<i64>,
    pub scores: Vec<f32>,
}

fn slot_set(
    conn: &Connection,
    sql: &str,
    space: Option<VectorSpace>,
) -> StoreResult<BTreeSet<i64>> {
    let mut statement = conn.prepare(sql).map_err(|e| sql_error(conn, e))?;
    let params: Vec<String> = space.into_iter().map(|s| s.to_string()).collect();
    let rows = statement
        .query_map(rusqlite::params_from_iter(params), |row| row.get(0))
        .map_err(|e| sql_error(conn, e))?;
    rows.collect::<Result<_, _>>()
        .map_err(|e| sql_error(conn, e))
}
pub fn verify(conn: &Connection, store: &VectorStore) -> StoreResult<VerificationReport> {
    let space = store.space();
    let hw = high_water(conn, space)?;
    let referenced = slot_set(
        conn,
        &format!("SELECT vec_slot FROM {space} WHERE vec_slot IS NOT NULL"),
        None,
    )?;
    let free = slot_set(
        conn,
        "SELECT slot FROM ci_vec_free WHERE space=?1",
        Some(space),
    )?;
    let overlap = referenced.intersection(&free).count();
    let out_of_range = referenced.iter().filter(|&&s| s < 0 || s >= hw).count();
    let mut segments = 0;
    let rows = store.manifest.segment_rows as u64;
    for index in store
        .segments
        .existing_indices((hw as u64).div_ceil(rows))?
    {
        if store.segments.open(index, false)?.is_some() {
            segments += 1;
        }
    }
    Ok(VerificationReport {
        high_water: hw,
        referenced: referenced.len(),
        free: free.len(),
        leaked: (hw - referenced.len() as i64 - free.len() as i64 + overlap as i64).max(0),
        out_of_range,
        double_booked: overlap,
        segments,
    })
}
pub fn live_scores(
    conn: &Connection,
    store: &VectorStore,
    query: &[f32],
) -> StoreResult<Option<LiveScores>> {
    let hw = high_water(conn, store.space())?;
    if hw == 0 {
        return Ok(None);
    }
    let count = usize::try_from(hw)
        .map_err(|_| StoreError::InvalidSlot("high-water exceeds address space"))?;
    let scores = store.scores(query, count)?;
    let free = slot_set(
        conn,
        "SELECT slot FROM ci_vec_free WHERE space=?1",
        Some(store.space()),
    )?;
    let mut live = LiveScores {
        slots: Vec::new(),
        scores: Vec::new(),
    };
    for (slot, score) in scores.into_iter().enumerate() {
        if !free.contains(&(slot as i64)) {
            live.slots.push(slot as i64);
            live.scores.push(score);
        }
    }
    Ok(Some(live))
}
