use ken_models::{ContextualRetrieval, EncoderSpec};
use ken_retrieval::{
    EntityKey, Passage, Result, RetrievalError,
    contextual::{ContextualRetriever, OwnerVectorSnapshot},
    query::Candidate,
    query_encoder::QueryEncoder,
    source_views::SourceViewSnapshot,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::value::RawValue;
use std::{collections::BTreeMap, rc::Rc};
#[derive(Deserialize)]
struct Root {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    input: Box<RawValue>,
}
#[derive(Deserialize)]
struct Source {
    owners: Vec<(EntityKey, Vec<Passage>)>,
    model: EncoderSpec,
    matrix: Vec<Vec<f32>>,
    snapshot_generation: i64,
}
fn source() -> Source {
    let root: Root =
        serde_json::from_str(include_str!("fixtures/selection-inputs-context.json")).unwrap();
    serde_json::from_str(root.cases[0].input.get()).unwrap()
}
struct Encoder;
impl QueryEncoder for Encoder {
    fn embed_query(&self, _: &PythonText) -> Result<Vec<f32>> {
        Ok(vec![1., 0.])
    }
}
fn candidate(owner: &(EntityKey, Vec<Passage>)) -> Candidate {
    Candidate {
        entity: owner.0.clone(),
        passages: owner.1.clone(),
        signals: BTreeMap::new(),
        owned_regions: Vec::new(),
    }
}
#[test]
fn standalone_source_view_enrichment_rejects_stale_foreign_and_empty_evidence_before_measurement() {
    let source = source();
    let mut view_model = source.model.clone();
    view_model.model_id.push_str("/views");
    let views = SourceViewSnapshot::new(
        view_model,
        source.snapshot_generation,
        source.owners.iter().map(|(e, _)| e.clone()).collect(),
        source
            .owners
            .iter()
            .map(|(_, p)| p[0].source_hash.clone())
            .collect(),
        source.matrix,
        BTreeMap::from([
            ("contract".into(), vec![0, 1, 2]),
            ("implementation".into(), vec![2, 0, 1]),
        ]),
        source.model,
    )
    .unwrap();
    for invalid in ["version", "owner", "empty"] {
        let mut candidates = vec![candidate(&source.owners[0]), candidate(&source.owners[1])];
        match invalid {
            "version" => candidates[1].passages[0].source_hash = "new-version".into(),
            "owner" => candidates[1].passages[0].entity = source.owners[2].0.clone(),
            _ => candidates[1].passages.clear(),
        }
        let before = candidates.clone();
        let error = views
            .enrich(&mut candidates, &[1., 0.], &[0., 1.])
            .unwrap_err();
        assert!(
            matches!(error, RetrievalError::Version(_)),
            "{invalid}: {error}"
        );
        assert_eq!(
            candidates, before,
            "an invalid source pool must not receive partial measurements"
        );
    }
    let mut valid = vec![candidate(&source.owners[1])];
    views.enrich(&mut valid, &[1., 0.], &[0., 1.]).unwrap();
    assert_eq!(valid[0].signals.len(), 4);
}
#[test]
fn contextual_proposals_revalidate_the_complete_current_owner_source() {
    let source = source();
    let snapshot = OwnerVectorSnapshot::new(
        source.model.clone(),
        source.snapshot_generation,
        source.owners.iter().map(|(e, _)| e.clone()).collect(),
        source
            .owners
            .iter()
            .map(|(_, p)| p[0].source_hash.clone())
            .collect(),
        source.matrix,
        1,
    )
    .unwrap();
    let runtime =
        ContextualRetriever::new(Rc::new(Encoder), source.model.clone(), snapshot, None).unwrap();
    let policy = ContextualRetrieval {
        model: source.model,
        channel_limit: 2,
        broad_limit: 8,
        projection_version: 1,
        view_model: None,
    };
    let scores = runtime
        .score(
            &"original".into(),
            &"original".into(),
            &source.owners,
            source.snapshot_generation,
            &policy,
        )
        .unwrap();
    for invalid in ["version", "owner", "empty", "missing"] {
        let mut changed = source.owners.clone();
        match invalid {
            "version" => changed[0].1[0].source_hash = "new-version".into(),
            "owner" => changed[0].1[0].entity = source.owners[1].0.clone(),
            "empty" => changed[0].1.clear(),
            _ => {
                changed.pop();
            }
        }
        let before = changed.clone();
        let error = scores.propose(&changed, 3).unwrap_err();
        assert!(
            matches!(error, RetrievalError::Version(_)),
            "{invalid}: {error}"
        );
        assert_eq!(changed, before);
    }
    assert_eq!(scores.propose(&source.owners, 3).unwrap().len(), 3);
}
