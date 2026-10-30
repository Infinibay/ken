//! Justification validation/persistence, with external check freshness supplied explicitly.
use crate::{Result, dependencies, invalid, wire};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
/// Observation from the native checks service. Absence is unknown, never success.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct CheckObservation {
    pub run_id: String,
    pub receipt_path: String,
    pub status: String,
    pub rules: Vec<String>,
    pub validity: Value,
    pub observations: Value,
}
pub fn prepare(data: &Value, root: Option<&Path>, checks: &[CheckObservation]) -> Result<Value> {
    wire::fields(
        data,
        &[
            "kind",
            "rationale",
            "evidence",
            "dependencies",
            "assumptions",
            "recheck",
            "check_runs",
        ],
        "justification fields: kind, rationale, evidence, dependencies, assumptions, recheck, check_runs",
    )?;
    let kind = data
        .get("kind")
        .map_or(Some("observation"), Value::as_str)
        .ok_or_else(|| invalid("unsupported justification kind"))?;
    if !["observation", "decision", "hypothesis", "derivation"].contains(&kind) {
        return Err(invalid("unsupported justification kind"));
    }
    let rationale = wire::string(&data["rationale"], "rationale", 4000, false)?;
    let recheck = wire::string(
        data.get("recheck").unwrap_or(&json!("")),
        "recheck",
        1000,
        true,
    )?;
    let assumptions = data.get("assumptions").cloned().unwrap_or(json!([]));
    let assumptions = assumptions
        .as_array()
        .filter(|a| a.len() <= 16)
        .ok_or_else(|| invalid("assumptions must be a list of at most 16 strings"))?
        .iter()
        .map(|s| wire::string(s, "assumption", 500, false))
        .collect::<Result<Vec<_>>>()?;
    let runs = data.get("check_runs").cloned().unwrap_or(json!([]));
    let runs = runs
        .as_array()
        .filter(|a| a.len() <= 8 && a.iter().all(Value::is_string))
        .ok_or_else(|| invalid("check_runs must contain at most eight receipt IDs"))?;
    let mut ids = Vec::<String>::new();
    for run in runs {
        let id = run.as_str().unwrap();
        if !ids.iter().any(|s| s == id) {
            ids.push(id.to_owned());
        }
    }
    let mut evidence = data
        .get("evidence")
        .cloned()
        .unwrap_or(json!([]))
        .as_array()
        .cloned()
        .ok_or_else(|| invalid("evidence must be a list of at most 16 file references"))?;
    for id in &ids {
        if root.is_none() {
            return Err(invalid("check receipts require a project root"));
        }
        let check = checks
            .iter()
            .find(|c| &c.run_id == id)
            .ok_or_else(|| invalid("check freshness unavailable; rerun ken_check"))?;
        if check.validity["state"] != "unchanged" {
            return Err(invalid(
                "check inputs changed before recording; rerun ken_check",
            ));
        }
        evidence.push(json!({"path":check.receipt_path,"note":"Immutable KQL2 check receipt; retain status, scope and uncertainty."}));
    }
    if evidence.len() > 16 {
        return Err(invalid(
            "evidence must be a list of at most 16 file references",
        ));
    }
    let mut specs = data
        .get("dependencies")
        .cloned()
        .unwrap_or(json!([]))
        .as_array()
        .filter(|a| a.len() <= 32)
        .cloned()
        .ok_or_else(|| invalid("dependencies must be a list of at most 32 file/tree references"))?;
    let mut clean = Vec::new();
    for item in evidence {
        wire::fields(
            &item,
            &["path", "note", "sha256"],
            "evidence fields: path, note, sha256",
        )?;
        let path = wire::string(&item["path"], "evidence path", 1000, false)?;
        let note = wire::string(
            item.get("note").unwrap_or(&json!("")),
            "evidence note",
            1000,
            true,
        )?;
        let mut spec = json!({"kind":"file","path":path});
        if let Some(hash) = item.get("sha256") {
            spec["sha256"] = hash.clone();
        }
        specs.push(spec);
        clean.push(json!({"path":path,"note":note}));
    }
    let dependencies = if let Some(root) = root {
        dependencies::capture(&json!(specs), root)?
    } else if specs.is_empty() {
        json!([])
    } else {
        return Err(invalid(
            "a project root is required to capture dependencies",
        ));
    };
    let mut result = json!({"version":1,"kind":kind,"rationale":rationale,"evidence":clean,"dependencies":dependencies,"assumptions":assumptions,"recheck":recheck});
    if !ids.is_empty() {
        result["check_runs"] = json!(ids);
    }
    Ok(result)
}
pub fn ensure_schema(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS cr_justifications(finding_id INTEGER PRIMARY KEY REFERENCES cr_findings(id) ON DELETE CASCADE,payload TEXT NOT NULL)")?;
    Ok(())
}
pub fn save(db: &Connection, finding_id: i64, data: Option<&Value>) -> Result<()> {
    db.execute(
        "DELETE FROM cr_justifications WHERE finding_id=?",
        [finding_id],
    )?;
    if let Some(data) = data {
        db.execute(
            "INSERT INTO cr_justifications VALUES(?,?)",
            params![finding_id, serde_json::to_string(data)?],
        )?;
    }
    Ok(())
}
pub fn project_root(db: &Connection) -> Option<PathBuf> {
    let mut stmt = db.prepare("PRAGMA database_list").ok()?;
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, String>(1)?, r.get::<_, String>(2)?)))
        .ok()?;
    for row in rows.flatten() {
        if row.0 == "main" && !row.1.is_empty() {
            let path = PathBuf::from(row.1);
            if path.parent()?.file_name()? == ".ken" {
                return path.parent()?.parent().map(Path::to_path_buf);
            }
        }
    }
    None
}
pub fn enrich(
    db: &Connection,
    hits: &[Value],
    root: Option<&Path>,
    checks: &[CheckObservation],
) -> Result<Vec<Value>> {
    if hits.is_empty() {
        return Ok(Vec::new());
    }
    if db
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE name='cr_justifications'",
            [],
            |r| r.get::<_, i64>(0),
        )
        .optional()?
        .is_none()
    {
        return Ok(hits.to_vec());
    }
    let inferred = project_root(db);
    let root = root.or(inferred.as_deref());
    let mut fingerprints = root.and_then(|root| {
        dependencies::Fingerprints::new(root, dependencies::Budget::default()).ok()
    });
    let mut out = Vec::new();
    for hit in hits {
        let topic = hit["topic"].as_str().unwrap_or("");
        let row=db.query_row("SELECT j.payload,f.content FROM cr_justifications j JOIN cr_findings f ON f.id=j.finding_id WHERE f.topic=?",[topic],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?))).optional()?;
        let Some((payload, content)) = row else {
            out.push(hit.clone());
            continue;
        };
        let (data, validity) = match serde_json::from_str::<Value>(&payload) {
            Ok(data) if data["version"] == 1 && data["dependencies"].is_array() => {
                let mut validity = dependencies::assess_with_fingerprints(
                    &data["dependencies"],
                    fingerprints.as_mut(),
                );
                if let Some(runs) = data.get("check_runs") {
                    let mut live = Vec::new();
                    let mut states =
                        vec![validity["state"].as_str().unwrap_or("unknown").to_owned()];
                    let mut issues = validity["issues"].as_array().cloned().unwrap_or_default();
                    if let Some(runs) = runs.as_array() {
                        for run in runs {
                            if let Some(check) = checks
                                .iter()
                                .find(|c| Some(c.run_id.as_str()) == run.as_str())
                            {
                                states.push(
                                    check.validity["state"]
                                        .as_str()
                                        .unwrap_or("unknown")
                                        .to_owned(),
                                );
                                if let Some(more) = check.validity["issues"].as_array() {
                                    issues.extend(more.iter().cloned());
                                }
                                live.push(json!({"run_id":check.run_id,"status":check.status,"rules":check.rules,"validity":check.validity["state"],"observations":check.observations}));
                            } else {
                                states.push("unknown".into());
                                issues.push(json!("check freshness unavailable"));
                            }
                        }
                    } else {
                        states.push("unknown".into());
                        issues.push(json!("invalid check receipt declarations"));
                    }
                    validity = json!({"state":if states.iter().any(|s|s=="stale"){"stale"}else if states.iter().any(|s|s=="unknown"){"unknown"}else{"unchanged"},"issues":issues,"checks":live,"scope":"Declared inputs; no KQL replay or verification of memory prose."});
                }
                (data, validity)
            }
            _ => (
                json!({}),
                json!({"state":"unknown","issues":["invalid justification record"]}),
            ),
        };
        let mut item = hit.clone();
        item["content"] = json!(content);
        item["justification"] = data;
        item["validity"] = validity;
        out.push(item);
    }
    Ok(out)
}
pub fn for_topics(
    db: &Connection,
    topics: &[String],
    root: Option<&Path>,
    checks: &[CheckObservation],
) -> Result<Vec<Value>> {
    let mut seen = std::collections::BTreeSet::new();
    let mut hits = Vec::new();
    for topic in topics {
        if !seen.insert(topic) {
            continue;
        }
        if let Some((topic, content)) = db
            .query_row(
                "SELECT topic,content FROM cr_findings WHERE topic=?",
                [topic],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
            )
            .optional()?
        {
            hits.push(json!({"topic":topic,"content":content}));
        }
    }
    enrich(db, &hits, root, checks)
}
