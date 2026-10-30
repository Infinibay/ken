//! Coordinate public memory/reasoning use; domains retain their rules and storage.
mod checks;
mod resources;
use crate::embedding::FindingVectorMath;
use ken_checks_application::ChecksApplication;
use ken_knowledge::{self as domain, Result, context, findings, reasoning, records};
pub use resources::EmbeddingResources;
use rusqlite::{Connection, OptionalExtension};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    rc::Rc,
};
/// The only optional failure boundary is document encoding while saving a note.
pub trait FindingEmbeddings {
    fn embed_finding(&self, db: &Connection, topic: &str, content: &str) -> Option<Vec<f32>>;
    fn embed_query(&self, db: &Connection, query: &str) -> Result<Vec<f32>>;
}
/// Hosts connect this port to a real active session, rather than inventing SQL state.
pub trait SessionSignals {
    fn dismiss(&self, target: &str, reason: &str) -> Result<Value>;
}
pub struct KnowledgeApplication {
    root: PathBuf,
    embeddings: Rc<dyn FindingEmbeddings>,
    signals: Rc<dyn SessionSignals>,
    checks: Option<ChecksApplication>,
    checks_provider: Option<Rc<dyn Fn() -> Result<ChecksApplication>>>,
    math: FindingVectorMath,
}
pub(super) fn error(error: impl std::fmt::Display) -> domain::Error {
    domain::Error::Invalid(error.to_string())
}
fn string<'a>(input: &'a Value, key: &str) -> &'a str {
    input[key].as_str().unwrap_or("")
}
fn limit(input: &Value) -> usize {
    input
        .get("limit")
        .and_then(Value::as_i64)
        .unwrap_or(5)
        .max(1) as usize
}
fn anchors(input: &Value) -> Value {
    let mut values = input
        .get("anchors")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    for (kind, key) in [
        ("file", "anchor_file"),
        ("symbol", "anchor_symbol"),
        ("tool", "anchor_tool"),
        ("error", "anchor_error"),
    ] {
        if let Some(value) = input.get(key).and_then(Value::as_str) {
            values.insert(kind.into(), json!(value));
        }
    }
    values.retain(|_, value| value.as_str().is_some_and(|s| !s.trim().is_empty()));
    Value::Object(values)
}
impl KnowledgeApplication {
    pub fn new(
        root: &Path,
        embeddings: Rc<dyn FindingEmbeddings>,
        signals: Rc<dyn SessionSignals>,
        checks: Option<ChecksApplication>,
    ) -> Result<Self> {
        let root = root.canonicalize()?;
        if !root.is_dir() {
            return Err(error("knowledge project root must be a directory"));
        }
        Ok(Self {
            root,
            embeddings,
            signals,
            checks,
            checks_provider: None,
            math: FindingVectorMath::default(),
        })
    }
    /// Construct checks only for an operation selecting a receipt declaration.
    pub fn with_checks_provider(
        mut self,
        provider: impl Fn() -> Result<ChecksApplication> + 'static,
    ) -> Self {
        self.checks_provider = Some(Rc::new(provider));
        self
    }
    fn checks_for(&self, ids: &[String]) -> Result<Option<ChecksApplication>> {
        if ids.is_empty() {
            return Ok(None);
        }
        if let Some(application) = &self.checks {
            return Ok(Some(application.clone()));
        }
        self.checks_provider
            .as_ref()
            .map(|provider| provider())
            .transpose()
    }
    pub fn remember(&self, db: &Connection, input: &Value, now: i64) -> Result<Value> {
        let action = input
            .get("action")
            .and_then(Value::as_str)
            .unwrap_or("save");
        match action {
            "dismiss" => self
                .signals
                .dismiss(string(input, "topic"), string(input, "reason")),
            "forget" => {
                findings::ensure_schema(db)?;
                findings::forget(db, string(input, "topic"), now, &self.math)
            }
            "save" => {
                if string(input, "content").trim().is_empty() {
                    return Ok(
                        json!({"ok":false,"error":"content is required when saving a finding"}),
                    );
                }
                let mut data = input.clone();
                if !data.is_object() {
                    return Ok(json!({"ok":false,"error":"finding input must be an object"}));
                }
                data["anchors"] = anchors(input);
                let run = string(input, "check_run");
                let mut ids = checks::run_ids(data.get("justification").unwrap_or(&Value::Null));
                if !run.is_empty() && !ids.iter().any(|id| id == run) {
                    ids.push(run.into());
                }
                let application = self.checks_for(&ids);
                if !run.is_empty() {
                    let application = application.as_ref().map_err(error)?;
                    data["justification"] = checks::attach(
                        application.as_ref(),
                        run,
                        input.get("justification").filter(|v| !v.is_null()),
                    )?;
                }
                let observations = checks::observations(
                    &self.root,
                    application
                        .as_ref()
                        .map(Option::as_ref)
                        .map_err(ToString::to_string),
                    &ids,
                );
                findings::ensure_schema(db)?;
                let mut encode =
                    |topic: &str, content: &str| self.embeddings.embed_finding(db, topic, content);
                findings::remember_with_embedding(
                    db,
                    &data,
                    &mut encode,
                    now,
                    Some(&self.root),
                    &observations,
                    &self.math,
                )
            }
            _ => Ok(
                json!({"ok":false,"error":format!("unknown action {action:?}"),"actions":["save","forget","dismiss"]}),
            ),
        }
    }
    pub fn recall(&self, db: &Connection, input: &Value, now: i64) -> Result<Value> {
        let detail = input
            .get("detail")
            .map_or(Some("full"), Value::as_str)
            .unwrap_or("");
        let max_chars = input
            .get("max_chars")
            .map_or(Some(3000), Value::as_u64)
            .and_then(|n| usize::try_from(n).ok())
            .unwrap_or(0);
        if !["full", "summary", "answer"].contains(&detail) || !(300..=20000).contains(&max_chars) {
            return Ok(
                json!({"ok":false,"error":"detail must be full/summary/answer; max_chars must be 300..20000"}),
            );
        }
        findings::ensure_schema(db)?;
        let selected = match self.select(db, input, detail, now) {
            Ok(value) => value,
            Err(error) => return Ok(json!({"ok":false,"error":error.to_string()})),
        };
        self.selected_view(db, &selected, detail, max_chars)
    }
    fn selected_view(
        &self,
        db: &Connection,
        selected: &Value,
        detail: &str,
        max_chars: usize,
    ) -> Result<Value> {
        // First discover only the selected memories' receipt declarations. Freshness
        // remains with ChecksApplication and is never inferred from stored witnesses.
        let full = context::recall_view(db, selected, Some(&self.root), "full", max_chars, &[])?;
        let ids = checks::run_ids(&full);
        let application = self.checks_for(&ids);
        let observations = checks::observations(
            &self.root,
            application
                .as_ref()
                .map(Option::as_ref)
                .map_err(ToString::to_string),
            &ids,
        );
        context::recall_view(
            db,
            &full,
            Some(&self.root),
            detail,
            max_chars,
            &observations,
        )
    }
    /// Ordinary recall is explicitly semantic, including an empty query argument.
    /// Its f64 threshold does not pass through JSON, which cannot represent +inf.
    pub fn recall_findings(
        &self,
        db: &Connection,
        query: &str,
        limit: usize,
        min_score: Option<f64>,
    ) -> Result<Value> {
        findings::ensure_schema(db)?;
        let selected = self.semantic_findings(db, query, limit, min_score)?;
        self.selected_view(db, &selected, "full", 3000)
    }
    fn semantic_findings(
        &self,
        db: &Connection,
        query: &str,
        limit: usize,
        min_score: Option<f64>,
    ) -> Result<Value> {
        let query = self.embeddings.embed_query(db, query)?;
        Ok(json!(findings::recall(
            db,
            &query,
            limit,
            min_score,
            Some(&self.root),
            &[],
            &self.math
        )?))
    }
    /// Exact topics never load a query model; only missing topics need fallback.
    pub fn related_findings(
        &self,
        db: &Connection,
        topic: &str,
        limit: usize,
        min_weight: f64,
        now: i64,
    ) -> Result<Value> {
        findings::ensure_schema(db)?;
        findings::ensure_graph(db, now, &self.math)?;
        let exists = db
            .query_row(
                "SELECT 1 FROM cr_findings WHERE topic=?",
                [topic.trim()],
                |r| r.get::<_, i64>(0),
            )
            .optional()?
            .is_some();
        let query = if exists {
            None
        } else {
            Some(self.embeddings.embed_query(db, topic)?)
        };
        findings::related(db, topic, limit, min_weight, query.as_deref(), &self.math)
    }
    pub fn file_findings(
        &self,
        db: &Connection,
        path: &str,
        expand: bool,
        limit: usize,
        now: i64,
    ) -> Result<Value> {
        findings::ensure_schema(db)?;
        findings::ensure_graph(db, now, &self.math)?;
        findings::for_file(db, path, expand, limit, Some(&self.root))
    }
    /// Rebuild all derived graph rows as one operation-owned write transaction.
    pub fn rebuild_findings_graph(&self, db: &Connection, now: i64) -> Result<Value> {
        findings::ensure_schema(db)?;
        findings::ensure_graph(db, now, &self.math)?;
        db.execute_batch("BEGIN IMMEDIATE")?;
        let rebuilt = findings::rebuild(db, now, &self.math);
        let mut result = match rebuilt {
            Ok(value) => {
                if let Err(error) = db.execute_batch("COMMIT") {
                    let _ = db.execute_batch("ROLLBACK");
                    return Err(error.into());
                }
                value
            }
            Err(error) => {
                let _ = db.execute_batch("ROLLBACK");
                return Err(error);
            }
        };
        result["edges"] = json!(db.query_row(
            "SELECT count(*) FROM cr_finding_edges",
            [],
            |r| r.get::<_, i64>(0)
        )?);
        result["refs"] = json!(
            db.query_row("SELECT count(*) FROM cr_finding_refs", [], |r| r
                .get::<_, i64>(0))?
        );
        Ok(result)
    }
    fn select(&self, db: &Connection, input: &Value, detail: &str, now: i64) -> Result<Value> {
        let anchors = anchors(input);
        let topic = string(input, "topic");
        let limit = limit(input);
        if anchors.as_object().is_some_and(|m| !m.is_empty()) {
            return Ok(json!(findings::by_anchor(db, &anchors, limit)?));
        }
        if detail == "answer" && !topic.is_empty() {
            return Ok(json!(records::for_topics(
                db,
                &[topic.into()],
                Some(&self.root),
                &[]
            )?));
        }
        if !topic.is_empty() {
            return self.related_findings(db, topic, limit, 0.3, now);
        }
        let path = string(input, "path");
        if !path.is_empty() {
            return self.file_findings(db, path, false, limit, now);
        }
        let query = string(input, "query");
        if !query.is_empty() {
            return self.semantic_findings(
                db,
                query,
                limit,
                input.get("min_score").and_then(Value::as_f64),
            );
        }
        let tag = string(input, "tag");
        Ok(json!(findings::list(
            db,
            limit,
            if tag.is_empty() { None } else { Some(tag) },
            Some(&self.root),
            &[]
        )?))
    }
    pub fn reason_record(&self, db: &Connection, input: &Value) -> Result<Value> {
        reasoning::ensure_schema(db)?;
        match reasoning::record(db, input) {
            Ok(value) => Ok(value),
            Err(error) => Ok(json!({"ok":false,"error":error.to_string()})),
        }
    }
    pub fn reason(
        &self,
        findings_db: &Connection,
        reasoning_db: &Connection,
        input: &Value,
        now: i64,
    ) -> Result<Value> {
        let question = string(input, "question");
        if question.trim().is_empty() || question.chars().count() > 4000 {
            return Ok(json!({"ok":false,"error":"question must contain 1..4000 characters"}));
        }
        if input.get("goal").is_none_or(Value::is_null) {
            let candidates = self.recall(findings_db, &json!({"query":question,"limit":5}), now)?;
            return Ok(
                json!({"status":"needs_interpretation","question":question,"candidates":candidates,"note":"These are retrieval candidates, not premises. Supply a scoped goal and record supported premises."}),
            );
        }
        reasoning::ensure_schema(reasoning_db)?;
        match reasoning::ask(reasoning_db, input) {
            Ok(mut value) => {
                value["question"] = json!(question);
                Ok(value)
            }
            Err(error) => Ok(json!({"ok":false,"error":error.to_string()})),
        }
    }
}
