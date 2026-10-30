//! Detached native semantic buckets. The wrapped graph remains the semantic owner.
use super::cache::{Memo, decode, encode};
use ken_program::{Entity, Fact, Operation, value::GraphValue};
use ken_query::execution::{
    Cancellation, ExecutionError, FactProbe, GraphRead, OperationProbe, Result, SourceProbe,
    values::SourceNode,
};
use serde::{Deserialize, Serialize};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::PathBuf,
    sync::Arc,
    time::Instant,
};
const MAX_ROWS: usize = 100000;
#[derive(Clone)]
pub struct BucketOptions {
    pub cache_path: Option<PathBuf>,
    pub revision: String,
    pub disk_bytes: u64,
    pub memory_bytes: u64,
    pub cancellation: Cancellation,
    pub deadline: Option<Instant>,
}
impl Default for BucketOptions {
    fn default() -> Self {
        Self {
            cache_path: None,
            revision: String::new(),
            disk_bytes: 256000000,
            memory_bytes: 64000000,
            cancellation: Default::default(),
            deadline: None,
        }
    }
}
#[derive(Clone, Default, Debug, Serialize)]
pub struct BucketMetrics {
    pub hits: u64,
    pub disk_hits: u64,
    pub builds: u64,
    pub fallback: u64,
    pub loaded_rows: u64,
    pub build_ms: f64,
    pub memory_bytes: u64,
    pub evictions: u64,
    pub cache_error: Option<String>,
}
#[derive(Serialize, Deserialize)]
enum Raw {
    Facts(Vec<Fact>),
    Operations(Vec<Operation>),
}
struct Entry {
    raw: Raw,
    subjects: BTreeMap<String, Vec<usize>>,
    objects: BTreeMap<String, Vec<usize>>,
    attrs: BTreeMap<(String, String), Vec<usize>>,
    bytes: u64,
}
impl Entry {
    fn new(raw: Raw, bytes: u64, check: &mut dyn FnMut() -> Result<()>) -> Result<Self> {
        let mut e = Self {
            raw,
            subjects: BTreeMap::new(),
            objects: BTreeMap::new(),
            attrs: BTreeMap::new(),
            bytes,
        };
        if let Raw::Facts(rows) = &e.raw {
            for (i, f) in rows.iter().enumerate() {
                check()?;
                e.subjects.entry(f.subject.clone()).or_default().push(i);
                e.objects.entry(f.object.clone()).or_default().push(i);
                for (k, v) in &f.attrs {
                    e.attrs
                        .entry((k.clone(), GraphValue::parse(v)?.comparison()))
                        .or_default()
                        .push(i);
                }
            }
        }
        Ok(e)
    }
    fn len(&self) -> usize {
        match &self.raw {
            Raw::Facts(r) => r.len(),
            Raw::Operations(r) => r.len(),
        }
    }
}
struct State {
    memo: Memo,
    memory: BTreeMap<String, Arc<Entry>>,
    lru: VecDeque<String>,
    bytes: u64,
    counts: BTreeMap<String, u64>,
    metrics: BucketMetrics,
}
pub struct CatalogBuckets<'a> {
    base: &'a dyn GraphRead,
    options: BucketOptions,
    state: RefCell<State>,
}
impl<'a> CatalogBuckets<'a> {
    pub fn new(base: &'a dyn GraphRead, options: BucketOptions) -> Result<Self> {
        let memo = Memo::new(
            options.cache_path.as_deref(),
            options.disk_bytes,
            &mut || poll(&options),
        )?;
        Ok(Self {
            base,
            options,
            state: RefCell::new(State {
                memo,
                memory: BTreeMap::new(),
                lru: VecDeque::new(),
                bytes: 0,
                counts: BTreeMap::new(),
                metrics: Default::default(),
            }),
        })
    }
    fn check(&self) -> Result<()> {
        poll(&self.options)?;
        self.base.check_snapshot()
    }
    pub fn metrics(&self) -> BucketMetrics {
        let state = self.state.borrow();
        let mut m = state.metrics.clone();
        m.memory_bytes = state.bytes;
        m.evictions = state.memo.evictions;
        m.cache_error = state.memo.error.clone();
        m
    }
    fn entry(&self, key: &str, build: impl FnOnce() -> Result<Raw>) -> Result<Arc<Entry>> {
        self.check()?;
        {
            let mut s = self.state.borrow_mut();
            if let Some(e) = s.memory.get(key).cloned() {
                s.metrics.hits += 1;
                s.lru.retain(|k| k != key);
                s.lru.push_back(key.into());
                return Ok(e);
            }
        }
        let begin = Instant::now();
        let stored = self
            .state
            .borrow_mut()
            .memo
            .get(key, &self.options.revision, &mut || self.check())?;
        let raw = stored
            .as_ref()
            .and_then(|bytes| decode::<Raw>(bytes, &mut || self.check()).ok());
        let (raw, bytes, disk) = if let Some(raw) = raw {
            (raw, stored.unwrap(), true)
        } else {
            let raw = build()?;
            let bytes = encode(&raw, &mut || self.check())?;
            self.state
                .borrow_mut()
                .memo
                .put(key, &self.options.revision, &bytes, &mut || self.check())?;
            (raw, bytes, false)
        };
        let entry = Arc::new(Entry::new(raw, bytes.len() as u64, &mut || self.check())?);
        self.check()?;
        let mut s = self.state.borrow_mut();
        s.metrics.loaded_rows += entry.len() as u64;
        if disk {
            s.metrics.disk_hits += 1;
        } else {
            s.metrics.builds += 1;
            s.metrics.build_ms += begin.elapsed().as_secs_f64() * 1000.;
        }
        if entry.bytes <= self.options.memory_bytes {
            while s.bytes.saturating_add(entry.bytes) > self.options.memory_bytes {
                let Some(old) = s.lru.pop_front() else {
                    break;
                };
                if let Some(e) = s.memory.remove(&old) {
                    s.bytes -= e.bytes;
                }
            }
            s.bytes += entry.bytes;
            s.memory.insert(key.into(), entry.clone());
            s.lru.push_back(key.into());
        }
        Ok(entry)
    }
    fn estimate(&self, probe: &FactProbe) -> Result<u64> {
        let key = serde_json::to_string(&(&probe.relation, &probe.object))
            .map_err(|e| ExecutionError::Invalid(e.to_string()))?;
        if let Some(count) = self.state.borrow().counts.get(&key) {
            return Ok(*count);
        }
        self.check()?;
        let count = self.base.count(probe)?;
        self.state.borrow_mut().counts.insert(key, count);
        Ok(count)
    }
    fn fact_entry(&self, p: &FactProbe) -> Result<Option<Arc<Entry>>> {
        self.check()?;
        let all = FactProbe::relation(&p.relation);
        let count = self.estimate(&all)?;
        let partition = if count <= MAX_ROWS as u64 {
            all
        } else if let Some(object) = &p.object {
            let selected = FactProbe {
                object: Some(object.clone()),
                ..all
            };
            if self.estimate(&selected)? > MAX_ROWS as u64 {
                return Ok(None);
            }
            selected
        } else {
            return Ok(None);
        };
        let key = format!(
            "facts:{}",
            serde_json::to_string(&(&partition.relation, &partition.object))
                .map_err(|e| ExecutionError::Invalid(e.to_string()))?
        );
        self.entry(&key, || {
            let mut rows = vec![];
            self.base.facts(&partition, &mut |f| {
                self.check()?;
                if rows.len() >= MAX_ROWS {
                    return Err(ExecutionError::Exhausted("catalog_bucket_rows"));
                }
                rows.push((*f).clone());
                Ok(())
            })?;
            Ok(Raw::Facts(rows))
        })
        .map(Some)
    }
}
fn poll(options: &BucketOptions) -> Result<()> {
    if options.cancellation.is_cancelled() {
        Err(ExecutionError::Exhausted("cancelled"))
    } else if options.deadline.is_some_and(|d| Instant::now() >= d) {
        Err(ExecutionError::Exhausted("timeout_ms"))
    } else {
        Ok(())
    }
}
impl GraphRead for CatalogBuckets<'_> {
    fn check_snapshot(&self) -> Result<()> {
        self.check()
    }
    fn source_snapshot_id(&self) -> i64 {
        self.base.source_snapshot_id()
    }
    fn source_units(
        &self,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(i64) -> Result<()>,
    ) -> Result<()> {
        self.check()?;
        self.base.source_units(check, visit)
    }
    fn source_node(&self, id: &str) -> Result<Option<Arc<SourceNode>>> {
        self.check()?;
        self.base.source_node(id)
    }
    fn source_scan(
        &self,
        p: &SourceProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<SourceNode>) -> Result<()>,
    ) -> Result<u64> {
        self.check()?;
        self.base.source_scan(p, check, visit)
    }
    fn source_properties(&self, node: &SourceNode) -> Result<BTreeMap<String, GraphValue>> {
        self.check()?;
        self.base.source_properties(node)
    }
    fn source_program(&self, unit: i64) -> Result<Option<Arc<ken_program::Program>>> {
        self.check()?;
        self.base.source_program(unit)
    }
    fn source_coverage(&self) -> Result<bool> {
        self.check()?;
        self.base.source_coverage()
    }
    fn operations_checked(
        &self,
        p: &OperationProbe,
        check: &mut dyn FnMut() -> Result<()>,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        check()?;
        self.operations(p, &mut |op| {
            check()?;
            visit(op)
        })
    }
    fn operations(
        &self,
        p: &OperationProbe,
        visit: &mut dyn FnMut(Arc<Operation>) -> Result<()>,
    ) -> Result<()> {
        self.check()?;
        let Some(owner) = p.owner.as_ref().filter(|_| p.region.is_none()) else {
            self.state.borrow_mut().metrics.fallback += 1;
            return self.base.operations_checked(p, &mut || self.check(), visit);
        };
        let key = format!(
            "operations:{}",
            serde_json::to_string(owner).map_err(|e| ExecutionError::Invalid(e.to_string()))?
        );
        let entry = self.entry(&key, || {
            let mut rows = vec![];
            self.base.operations_checked(
                &OperationProbe {
                    owner: Some(owner.clone()),
                    ..Default::default()
                },
                &mut || self.check(),
                &mut |op| {
                    self.check()?;
                    if rows.len() >= MAX_ROWS {
                        return Err(ExecutionError::Exhausted("catalog_bucket_rows"));
                    }
                    rows.push((*op).clone());
                    Ok(())
                },
            )?;
            Ok(Raw::Operations(rows))
        });
        let entry = match entry {
            Err(ExecutionError::Exhausted("catalog_bucket_rows")) => {
                self.state.borrow_mut().metrics.fallback += 1;
                return self.base.operations_checked(p, &mut || self.check(), visit);
            }
            other => other?,
        };
        let Raw::Operations(rows) = &entry.raw else {
            return Err(ExecutionError::Storage("invalid operation bucket".into()));
        };
        for op in rows {
            self.check()?;
            if p.id.as_ref().is_none_or(|id| id == &op.id)
                && p.kind.as_ref().is_none_or(|k| k == &op.kind)
            {
                visit(Arc::new(op.clone()))?;
            }
        }
        Ok(())
    }
    fn facts(&self, p: &FactProbe, visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>) -> Result<()> {
        self.check()?;
        let Some(entry) = self.fact_entry(p)? else {
            self.state.borrow_mut().metrics.fallback += 1;
            return self.base.facts(p, &mut |f| {
                self.check()?;
                visit(f)
            });
        };
        let Raw::Facts(rows) = &entry.raw else {
            return Err(ExecutionError::Storage("invalid fact bucket".into()));
        };
        let mut postings = vec![];
        if let Some(s) = &p.subject {
            postings.push(entry.subjects.get(s).map_or(&[][..], Vec::as_slice));
        }
        if let Some(o) = &p.object {
            postings.push(entry.objects.get(o).map_or(&[][..], Vec::as_slice));
        }
        if let Some(k) = &p.attribute {
            postings.push(entry.attrs.get(k).map_or(&[][..], Vec::as_slice));
        }
        let selected: Box<dyn Iterator<Item = usize> + '_> =
            if let Some(ids) = postings.iter().min_by_key(|v| v.len()) {
                Box::new(ids.iter().copied())
            } else {
                Box::new(0..rows.len())
            };
        for i in selected {
            self.check()?;
            let f = &rows[i];
            if p.subject.as_ref().is_none_or(|s| s == &f.subject)
                && p.object.as_ref().is_none_or(|o| o == &f.object)
                && p.attribute.as_ref().is_none_or(|(k, v)| {
                    f.attrs
                        .get(k)
                        .and_then(|raw| GraphValue::parse(raw).ok())
                        .is_some_and(|value| value.comparison() == *v)
                })
            {
                visit(Arc::new(f.clone()))?;
            }
        }
        Ok(())
    }
    fn count(&self, p: &FactProbe) -> Result<u64> {
        let mut count = 0;
        self.facts(p, &mut |_| {
            count += 1;
            Ok(())
        })?;
        Ok(count)
    }
    fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
        self.check()?;
        self.base.entity(id)
    }
    fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        self.check()?;
        self.base.entity_ids(visit)
    }
    fn capabilities(&self) -> &BTreeSet<String> {
        self.base.capabilities()
    }
    fn relations(&self) -> &BTreeSet<String> {
        self.base.relations()
    }
}
