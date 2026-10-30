//! Relations delegate to navigation, historical evidence and source inspection.
use super::{ToolReply, live::LiveTools};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    tool_output::Document,
};
use ken_search::navigation::IndexNavigation;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Related {
    target: String,
    relation: String,
    #[serde(default = "ten")]
    limit: i64,
    #[serde(default = "one")]
    depth: i64,
    #[serde(default)]
    full: bool,
    #[serde(default)]
    min_confidence: f64,
    #[serde(default = "dot")]
    path: String,
    #[serde(default)]
    from_path: String,
    #[serde(default = "timeout")]
    timeout_ms: f64,
}
fn ten() -> i64 {
    10
}
fn one() -> i64 {
    1
}
fn dot() -> String {
    ".".into()
}
fn timeout() -> f64 {
    10000.
}
fn relative(paths: &ProjectPaths, value: &str) -> Result<String, String> {
    let context = DiscoveryContext::from_process().map_err(|e| e.to_string())?;
    let path = paths
        .resolve_inside(Path::new(value), &context)
        .map_err(|e| e.to_string())?;
    let value = path
        .strip_prefix(paths.root())
        .map_err(|e| e.to_string())?
        .to_string_lossy()
        .into_owned();
    Ok(if value.is_empty() { ".".into() } else { value })
}
fn attach(response: &Value, key: &str, raw: Box<RawValue>) -> Result<String, String> {
    let mut fields: BTreeMap<String, Box<RawValue>> =
        serde_json::from_str(&serde_json::to_string(response).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    fields.insert(key.into(), raw);
    serde_json::to_string(&fields).map_err(|e| e.to_string())
}
fn presentation(raw: String, format: &str, full: bool) -> Result<ToolReply, String> {
    if format == "json" {
        return Ok(ToolReply::Json(raw));
    }
    match Document::parse_json(&raw) {
        Ok(document) => super::present(&document, "ken_related", format, full),
        Err(_) => Ok(ToolReply::Json(raw)),
    }
}
pub(super) fn call(
    paths: &ProjectPaths,
    request: Related,
    live: &mut LiveTools,
    format: &str,
) -> Result<ToolReply, String> {
    if request.relation == "checks" {
        let report = super::checks::application(paths, live)?
            .related(
                &relative(paths, &request.target)?,
                usize::try_from(request.limit).map_err(|_| "limit must be positive")?,
            )
            .map_err(|e| e.to_string())?;
        return presentation(report.json().into(), format, request.full);
    }
    if matches!(request.relation.as_str(), "impact" | "roles" | "available") {
        let catalog =
            ken_structural::application::catalog::Catalog::packaged().map_err(|e| e.to_string())?;
        let input = ken_structural::application::inspection::InspectRequest {
            target: request.target,
            relation: request.relation.clone(),
            path: request.path,
            depth: usize::try_from(request.depth).map_err(|_| "depth must be positive")?,
            limit: usize::try_from(request.limit).map_err(|_| "limit must be positive")?,
            timeout_ms: request.timeout_ms,
            full: request.full,
            from_path: request.from_path,
        };
        let result = ken_structural::application::inspection::inspect_native(
            paths.root(),
            &input,
            live.shared_catalog()?,
            catalog.libraries().clone(),
        )
        .map_err(|e| e.to_string())?;
        let raw = if request.relation == "impact" {
            let application = super::checks::application(paths, live)?;
            let selected = result["targets"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|target| target["path"].as_str())
                .collect::<BTreeSet<_>>();
            let reports = selected
                .into_iter()
                .map(|path| {
                    application
                        .related(path, input.limit)
                        .map_err(|e| e.to_string())
                })
                .collect::<Result<Vec<_>, _>>()?;
            attach(
                &result,
                "contracts",
                serde_json::value::to_raw_value(&reports).map_err(|e| e.to_string())?,
            )?
        } else {
            serde_json::to_string(&result).map_err(|e| e.to_string())?
        };
        return presentation(raw, format, request.full);
    }
    let navigation = IndexNavigation::open(paths).map_err(|e| e.to_string())?;
    if matches!(
        request.relation.as_str(),
        "callers" | "callees" | "subtypes" | "supertypes"
    ) {
        let result = live.related(
            &navigation,
            &request.target,
            &request.relation,
            request.min_confidence,
            request.limit,
        )?;
        return super::present(&result, "ken_related", format, request.full);
    }
    if matches!(
        request.relation.as_str(),
        "cochange" | "blast_radius" | "clones"
    ) {
        let target = relative(paths, &request.target)?;
        let database = ken_store::ProjectDatabase::open(&paths.db()).map_err(|e| e.to_string())?;
        let conn = database.connection();
        let result = match request.relation.as_str() {
            "cochange" => ken_history::cochange::cochange(
                conn,
                &target,
                Some(paths.root()),
                &ken_history::cochange::CochangeOptions {
                    min_confidence: request.min_confidence,
                    limit: request.limit,
                    ..Default::default()
                },
            ),
            "clones" => ken_history::clones::clones(
                conn,
                Some(&target),
                None,
                Some(paths.root()),
                &ken_history::clones::CloneOptions {
                    limit: request.limit,
                    ..Default::default()
                },
            ),
            _ => ken_history::graphs::blast_radius(
                conn,
                &target,
                request.depth.max(1),
                &navigation,
                Some(paths.root()),
                &Default::default(),
            ),
        }
        .map_err(|e| e.to_string())?;
        let raw = if request.relation == "blast_radius" {
            let report = super::checks::application(paths, live)?
                .related(
                    &target,
                    usize::try_from(request.limit).map_err(|_| "limit must be positive")?,
                )
                .map_err(|e| e.to_string())?;
            attach(
                &result,
                "contracts",
                RawValue::from_string(report.json().into()).map_err(|e| e.to_string())?,
            )?
        } else {
            serde_json::to_string(&result).map_err(|e| e.to_string())?
        };
        return presentation(raw, format, request.full);
    }
    if !matches!(request.relation.as_str(), "neighbors" | "imports") {
        return presentation(json!({"ok":false,"error":format!("unknown relation {:?}",request.relation),"relations":["neighbors","imports","callers","callees","subtypes","supertypes","cochange","blast_radius","clones","checks","impact","roles","available"]}).to_string(),format,request.full);
    }
    let result = navigation
        .related(
            &request.target,
            &request.relation,
            request.depth,
            request.limit,
        )
        .map_err(|e| e.to_string())?;
    super::present(&result, "ken_related", format, request.full)
}
