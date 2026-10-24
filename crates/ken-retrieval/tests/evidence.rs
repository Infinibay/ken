use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    Result,
    evidence::{
        EvidenceOptions, complete_evidence, complete_owned_context, entity_extent, refine_evidence,
        source_bounds, verified_lines,
    },
    query::{CodeMatch, SearchRequest},
    ranking::RelevanceJudge,
    source_evidence::refine_source_evidence,
    source_snapshot::{SourceAuthority, SourceResult},
    stemming::WordStemmer,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    sync::{Arc, Mutex},
};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: Option<Value>,
    error: Option<Value>,
    #[serde(default)]
    calls: Vec<Value>,
}
#[derive(Deserialize)]
struct Input {
    files: BTreeMap<String, Vec<u8>>,
    matches: Vec<CodeMatch>,
    request: SearchRequest,
    operation: String,
    options: EvidenceOptions,
    judge: JudgeOptions,
    expanded_query: PythonText,
    stems: BTreeMap<String, String>,
    mutation: Option<Mutation>,
    implementation: Option<bool>,
}
#[derive(Deserialize)]
struct JudgeOptions {
    mode: String,
    #[serde(default)]
    needles: Vec<String>,
}
#[derive(Deserialize)]
struct Mutation {
    op: String,
    path: String,
    bytes: Vec<u8>,
}
type Calls = Arc<Mutex<Vec<Value>>>;
struct Judge<'a> {
    options: &'a JudgeOptions,
    calls: Calls,
}
impl RelevanceJudge for Judge<'_> {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>> {
        self.calls.lock().unwrap().push(
            json!({"operation":"judge","query":query,"documents":documents,"purpose":purpose}),
        );
        Ok(match self.options.mode.as_str() {
            "contains" => documents
                .iter()
                .map(|doc| {
                    if self
                        .options
                        .needles
                        .iter()
                        .all(|word| doc.to_utf8().unwrap().contains(word))
                    {
                        3.
                    } else {
                        -1.
                    }
                })
                .collect(),
            "ties" => vec![0.; documents.len()],
            "negative" => (0..documents.len()).map(|i| -((i + 1) as f64)).collect(),
            "wrong-size" => vec![0.; documents.len() + 1],
            "nan" => vec![f64::NAN; documents.len()],
            "inf" => vec![f64::INFINITY; documents.len()],
            _ => panic!("unknown input-only judge"),
        })
    }
}
struct Stem<'a> {
    replacements: &'a BTreeMap<String, String>,
    calls: Calls,
}
impl WordStemmer for Stem<'_> {
    fn stem(&self, _word: &PythonText) -> Result<PythonText> {
        panic!("lexical selector must batch vocabulary")
    }
    fn stem_words(&self, words: &[PythonText]) -> Result<Vec<PythonText>> {
        self.calls
            .lock()
            .unwrap()
            .push(json!({"operation":"stem","words":words}));
        Ok(words
            .iter()
            .map(|word| {
                self.replacements
                    .get(&word.to_utf8().unwrap())
                    .map_or_else(|| word.clone(), |v| v.as_str().into())
            })
            .collect())
    }
}
type Outcome<T> = std::result::Result<T, (String, String)>;
fn source<T>(value: SourceResult<T>) -> Outcome<T> {
    value.map_err(|e| (e.kind().into(), e.to_string()))
}
fn native<T>(value: Result<T>) -> Outcome<T> {
    value.map_err(|e| ("ValueError".into(), e.to_string()))
}
fn corpus(family: &str) -> Corpus {
    let raw = if let Some(directory) = std::env::var_os("KEN_PIECE_REFERENCE_DIR") {
        fs::read_to_string(
            std::path::PathBuf::from(directory).join(format!("piece-reference-{family}.json")),
        )
        .unwrap()
    } else {
        use std::io::Read;
        let mut raw = String::new();
        let bytes: &[u8] = match family {
            "evidence" => include_bytes!("fixtures/piece-reference-evidence-linux-x86_64.json.gz"),
            "evidence-edges" => {
                include_bytes!("fixtures/piece-reference-evidence-edges-linux-x86_64.json.gz")
            }
            _ => panic!("unknown original evidence family"),
        };
        flate2::read::GzDecoder::new(bytes)
            .read_to_string(&mut raw)
            .unwrap();
        raw
    };
    serde_json::from_str(&raw).unwrap()
}
#[test]
fn evidence_refinement_preserves_owner_order_and_source_budget() {
    let primary = corpus("evidence");
    let edges = corpus("evidence-edges");
    assert_eq!(primary.cases.len(), 86);
    assert_eq!(edges.cases.len(), 2);
    for case in primary.cases.into_iter().chain(edges.cases) {
        let temporary = tempfile::tempdir().unwrap();
        let root = temporary.path().join("project");
        fs::create_dir(&root).unwrap();
        let data = case.input;
        for (name, bytes) in &data.files {
            let target = root.join(name);
            fs::create_dir_all(target.parent().unwrap()).unwrap();
            fs::write(target, bytes).unwrap();
        }
        let context = DiscoveryContext {
            cwd: root.clone(),
            forced_root: None,
            home: None,
        };
        let authority = SourceAuthority::new(&ProjectPaths::at(&root, &context).unwrap()).unwrap();
        if let Some(mutation) = &data.mutation {
            let target = root.join(&mutation.path);
            match mutation.op.as_str() {
                "write" => fs::write(target, &mutation.bytes).unwrap(),
                "symlink" => {
                    let outside = temporary.path().join("outside.py");
                    fs::write(&outside, "outside fixture\n").unwrap();
                    fs::remove_file(&target).unwrap();
                    std::os::unix::fs::symlink(outside, target).unwrap();
                }
                "replace-root" => {
                    fs::rename(&root, temporary.path().join("old-project")).unwrap();
                    fs::create_dir(&root).unwrap();
                    fs::create_dir_all(target.parent().unwrap()).unwrap();
                    fs::write(target, &mutation.bytes).unwrap();
                }
                _ => panic!("unsupported source mutation"),
            }
        }
        let calls: Calls = Default::default();
        let before = data.matches.clone();
        let owner = &data.matches[0];
        let observed = (|| -> Outcome<Value> {
            let value = match data.operation.as_str() {
                "verified" => json!(source(verified_lines(&authority, owner))?),
                "extent" => json!(native(entity_extent(owner))?),
                "bounds" => {
                    let text = std::str::from_utf8(&data.files[&owner.entity.path]).unwrap();
                    json!(native(source_bounds(
                        owner,
                        &owner.evidence[0],
                        ken_text::unicode::splitlines(text).len(),
                        data.implementation.unwrap_or(true)
                    ))?)
                }
                "complete-owner" => json!(source(complete_owned_context(owner, &authority))?),
                "complete" => json!(native(complete_evidence(
                    &data.matches,
                    &authority,
                    &data.request
                ))?),
                "refine" => json!(native(refine_evidence(
                    &data.matches,
                    &authority,
                    &data.request,
                    &Judge {
                        options: &data.judge,
                        calls: calls.clone()
                    },
                    &data.options
                ))?),
                "lexical" => json!(native(refine_source_evidence(
                    &data.matches,
                    &authority,
                    &data.request,
                    &data.expanded_query,
                    &Stem {
                        replacements: &data.stems,
                        calls: calls.clone()
                    }
                ))?),
                _ => panic!("unsupported evidence observation"),
            };
            assert_eq!(data.matches, before, "input mutated {}", case.id);
            Ok(json!({"value":value,"calls":*calls.lock().unwrap(),"unchanged":true}))
        })();
        if let Some(error) = case.error {
            let (kind, message) = observed
                .err()
                .unwrap_or_else(|| panic!("expected original error {}", case.id));
            assert_eq!(kind, error["type"], "kind {}", case.id);
            assert_eq!(message, error["message"], "message {}", case.id);
            assert_eq!(
                *calls.lock().unwrap(),
                case.calls,
                "error calls {}",
                case.id
            );
        } else {
            assert_eq!(observed.unwrap(), case.result.unwrap(), "{}", case.id);
        }
    }
}
