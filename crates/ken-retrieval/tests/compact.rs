use flate2::read::GzDecoder;
use ken_retrieval::{
    compact::render,
    presentation::{
        DisplayedSource, Evidence, OwnerResult, PieceResult, SearchResponse, SearchResult,
    },
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read};

#[derive(Deserialize)]
struct Corpus {
    format: String,
    reference_fingerprint: String,
    rows: Vec<Row>,
}
#[derive(Deserialize)]
struct Row {
    id: String,
    response: OriginalResponse,
    diagnostics: bool,
    text: String,
}
#[derive(Deserialize)]
struct OriginalResponse {
    query: PythonText,
    #[serde(flatten)]
    body: BTreeMap<String, Value>,
}

// Construct typed production output from independent original observations. This
// adapter supplies no formatting, evidence selection or expected-text logic.
fn response(query: &PythonText, value: &Value) -> SearchResponse {
    SearchResponse {
        query: query.clone(),
        profile_version: value["profile_version"].as_str().unwrap().into(),
        warnings: serde_json::from_value(value["warnings"].clone()).unwrap(),
        truncated: value["truncated"].as_bool().unwrap(),
        omitted_count: value["omitted_count"].as_u64().unwrap() as usize,
        results: value["results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| {
                let source = DisplayedSource {
                    path: v["path"].as_str().unwrap().into(),
                    entity: serde_json::from_value(v["entity"].clone()).unwrap(),
                    entity_span: serde_json::from_value(v["entity_span"].clone()).unwrap(),
                    source_hash: v["source_hash"].as_str().unwrap().into(),
                    stale: v["stale"].as_bool().unwrap(),
                    truncated: v["truncated"].as_bool().unwrap(),
                    evidence: v["evidence"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|e| Evidence {
                            start_line: e["start_line"].as_u64().unwrap() as usize,
                            end_line: e["end_line"].as_u64().unwrap() as usize,
                            content: e["content"].as_str().unwrap().into(),
                        })
                        .collect(),
                };
                if let Some(kind) = v["piece_kind"].as_str() {
                    SearchResult::Piece(PieceResult {
                        source,
                        piece_kind: kind.into(),
                        module_name: v.get("module_name").map(|n| n.as_str().map(str::to_owned)),
                        signals: v.get("signals").cloned(),
                    })
                } else {
                    SearchResult::Owner(OwnerResult {
                        source,
                        language: v["language"].as_str().unwrap().into(),
                        ranking_score: v["ranking_score"].as_f64().unwrap(),
                        signals: v
                            .get("signals")
                            .map(|s| serde_json::from_value(s.clone()).unwrap()),
                        matches: v
                            .get("matches")
                            .map(|m| serde_json::from_value(m.clone()).unwrap()),
                    })
                }
            })
            .collect(),
    }
}

#[test]
fn compact_text_preserves_all_independently_observed_fragments_and_diagnostics() {
    let bytes = include_bytes!("fixtures/public-render-reference.json.gz");
    assert_eq!(bytes.len(), 8143);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "fa4404f58bc226c3015b70f5e0231591b36c11462173db20124fc1a9439bf5c8"
    );
    let mut raw = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut raw).unwrap();
    let corpus: Corpus = serde_json::from_str(&raw).unwrap();
    assert_eq!(corpus.format, "ken-public-render-original/1");
    assert_eq!(
        corpus.reference_fingerprint,
        "5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038"
    );
    assert_eq!(corpus.rows.len(), 256);
    for row in corpus.rows {
        let response = response(
            &row.response.query,
            &serde_json::to_value(row.response.body).unwrap(),
        );
        let before = serde_json::to_string(&response).unwrap();
        assert_eq!(render(&response, row.diagnostics), row.text, "{}", row.id);
        assert_eq!(
            serde_json::to_string(&response).unwrap(),
            before,
            "rendering mutated {}",
            row.id
        );
    }
}
