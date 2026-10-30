//! Native bucket storage is a detached GraphRead adapter, preserving source semantics.
use ken_program::{Entity, Fact, Operation};
use ken_query::execution::{Cancellation, ExecutionError, FactProbe, GraphRead, OperationProbe};
use ken_structural::application::exploration::buckets::{BucketOptions, CatalogBuckets};
use std::{cell::Cell, collections::BTreeSet, path::PathBuf, sync::Arc};
#[derive(Default)]
struct Base {
    facts: Vec<Arc<Fact>>,
    operations: Vec<Arc<Operation>>,
    reads: Cell<usize>,
    fail_reads: Cell<bool>,
    caps: BTreeSet<String>,
    relations: BTreeSet<String>,
}
impl Base {
    fn fixture() -> Self {
        Self {
            facts: [("b", ""), ("a", "v"), ("b", "v"), ("b", "v")]
                .into_iter()
                .map(|(s, o)| {
                    Arc::new(Fact {
                        subject: s.into(),
                        relation: "R".into(),
                        object: o.into(),
                        attrs: Default::default(),
                        evidence: vec!["source-evidence".into()],
                    })
                })
                .collect(),
            operations: vec![Arc::new(Operation {
                id: "call".into(),
                kind: "CALL".into(),
                native_kind: "call".into(),
                parent: None,
                role: "value".into(),
                start: 0,
                end: 3,
                line: 1,
                owner: "owner".into(),
                attrs: Default::default(),
            })],
            relations: BTreeSet::from(["R".into()]),
            ..Default::default()
        }
    }
}
impl GraphRead for Base {
    fn facts(
        &self,
        p: &FactProbe,
        visit: &mut dyn FnMut(Arc<Fact>) -> ken_query::execution::Result<()>,
    ) -> ken_query::execution::Result<()> {
        assert!(
            !self.fail_reads.get(),
            "retained bucket fell back to base fact scan"
        );
        self.reads.set(self.reads.get() + 1);
        for f in &self.facts {
            if f.relation == p.relation
                && p.subject.as_ref().is_none_or(|s| s == &f.subject)
                && p.object.as_ref().is_none_or(|o| o == &f.object)
            {
                visit(f.clone())?;
            }
        }
        Ok(())
    }
    fn count(&self, p: &FactProbe) -> ken_query::execution::Result<u64> {
        Ok(self
            .facts
            .iter()
            .filter(|f| {
                f.relation == p.relation
                    && p.subject.as_ref().is_none_or(|s| s == &f.subject)
                    && p.object.as_ref().is_none_or(|o| o == &f.object)
            })
            .count() as u64)
    }
    fn operations(
        &self,
        p: &OperationProbe,
        visit: &mut dyn FnMut(Arc<Operation>) -> ken_query::execution::Result<()>,
    ) -> ken_query::execution::Result<()> {
        assert!(
            !self.fail_reads.get(),
            "retained owner bucket reread operations"
        );
        self.reads.set(self.reads.get() + 1);
        for op in &self.operations {
            if p.owner.as_ref().is_none_or(|v| v == &op.owner)
                && p.id.as_ref().is_none_or(|v| v == &op.id)
                && p.kind.as_ref().is_none_or(|v| v == &op.kind)
            {
                visit(op.clone())?;
            }
        }
        Ok(())
    }
    fn entity(&self, _: &str) -> ken_query::execution::Result<Option<Arc<Entity>>> {
        Ok(None)
    }
    fn entity_ids(
        &self,
        _: &mut dyn FnMut(&str) -> ken_query::execution::Result<()>,
    ) -> ken_query::execution::Result<()> {
        Ok(())
    }
    fn capabilities(&self) -> &BTreeSet<String> {
        &self.caps
    }
    fn relations(&self) -> &BTreeSet<String> {
        &self.relations
    }
}
fn options(path: Option<PathBuf>, revision: &str) -> BucketOptions {
    BucketOptions {
        cache_path: path,
        revision: revision.into(),
        ..Default::default()
    }
}
fn facts(graph: &dyn GraphRead, subject: Option<&str>, object: Option<&str>) -> Vec<String> {
    let mut result = vec![];
    graph
        .facts(
            &FactProbe {
                relation: "R".into(),
                subject: subject.map(Into::into),
                object: object.map(Into::into),
                attribute: None,
            },
            &mut |f| {
                assert_eq!(f.evidence, vec!["source-evidence"]);
                result.push(f.subject.clone());
                Ok(())
            },
        )
        .unwrap();
    result
}
#[test]
fn endpoint_postings_preserve_duplicate_source_order_and_avoid_repeated_base_reads() {
    let base = Base::fixture();
    let graph = CatalogBuckets::new(&base, options(None, "r1")).unwrap();
    assert_eq!(facts(&graph, None, Some("v")), vec!["a", "b", "b"]);
    let reads = base.reads.get();
    assert!(reads > 0);
    assert_eq!(facts(&graph, Some("b"), Some("v")), vec!["b", "b"]);
    assert_eq!(base.reads.get(), reads);
    assert!(graph.metrics().hits > 0);
}
#[test]
fn persisted_owner_operations_are_detached_and_reusable_without_base_reads() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("buckets.sqlite");
    let base = Base::fixture();
    let probe = OperationProbe {
        owner: Some("owner".into()),
        ..Default::default()
    };
    {
        let graph = CatalogBuckets::new(&base, options(Some(path.clone()), "r1")).unwrap();
        let mut ids = vec![];
        graph
            .operations(&probe, &mut |op| {
                ids.push(op.id.clone());
                Ok(())
            })
            .unwrap();
        assert_eq!(ids, vec!["call"]);
    }
    base.fail_reads.set(true);
    let graph = CatalogBuckets::new(&base, options(Some(path), "r1")).unwrap();
    let mut ids = vec![];
    graph
        .operations(&probe, &mut |op| {
            ids.push(op.id.clone());
            Ok(())
        })
        .unwrap();
    assert_eq!(ids, vec!["call"]);
    assert_eq!(graph.metrics().disk_hits, 1);
}
#[test]
fn revision_and_checksum_changes_rebuild_instead_of_reusing_stale_buckets() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("buckets.sqlite");
    let mut base = Base::fixture();
    {
        let graph = CatalogBuckets::new(&base, options(Some(path.clone()), "r1")).unwrap();
        assert_eq!(facts(&graph, None, None).len(), 4);
    }
    base.facts.truncate(1);
    {
        let graph = CatalogBuckets::new(&base, options(Some(path.clone()), "r2")).unwrap();
        assert_eq!(facts(&graph, None, None).len(), 1);
        assert_eq!(graph.metrics().disk_hits, 0);
    }
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute("UPDATE buckets SET digest='damaged'", [])
        .unwrap();
    drop(db);
    let graph = CatalogBuckets::new(&base, options(Some(path), "r2")).unwrap();
    assert_eq!(facts(&graph, None, None).len(), 1);
    assert_eq!(graph.metrics().disk_hits, 0);
    assert_eq!(graph.metrics().builds, 1);
}
#[test]
fn canceled_and_interrupted_bucket_builds_never_publish_partial_rows() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("buckets.sqlite");
    let cancel = Cancellation::default();
    cancel.cancel();
    let base = Base::fixture();
    let result = CatalogBuckets::new(
        &base,
        BucketOptions {
            cancellation: cancel,
            cache_path: Some(path.clone()),
            ..options(None, "r1")
        },
    );
    assert!(result.is_err());
    assert!(!path.exists());
    struct Interrupted(Base);
    impl GraphRead for Interrupted {
        fn facts(
            &self,
            _: &FactProbe,
            visit: &mut dyn FnMut(Arc<Fact>) -> ken_query::execution::Result<()>,
        ) -> ken_query::execution::Result<()> {
            visit(self.0.facts[0].clone())?;
            Err(ExecutionError::Exhausted("timeout_ms"))
        }
        fn count(&self, _: &FactProbe) -> ken_query::execution::Result<u64> {
            Ok(4)
        }
        fn entity(&self, _: &str) -> ken_query::execution::Result<Option<Arc<Entity>>> {
            Ok(None)
        }
        fn entity_ids(
            &self,
            _: &mut dyn FnMut(&str) -> ken_query::execution::Result<()>,
        ) -> ken_query::execution::Result<()> {
            Ok(())
        }
        fn capabilities(&self) -> &BTreeSet<String> {
            &self.0.caps
        }
        fn relations(&self) -> &BTreeSet<String> {
            &self.0.relations
        }
    }
    let interrupted = Interrupted(Base::fixture());
    let graph = CatalogBuckets::new(&interrupted, options(Some(path.clone()), "r1")).unwrap();
    assert!(
        graph
            .facts(&FactProbe::relation("R"), &mut |_| Ok(()))
            .is_err()
    );
    drop(graph);
    let graph = CatalogBuckets::new(&base, options(Some(path), "r1")).unwrap();
    assert_eq!(facts(&graph, None, None).len(), 4);
    assert_eq!(graph.metrics().disk_hits, 0);
    assert_eq!(graph.metrics().builds, 1);
}
