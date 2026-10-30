//! Live structural tool routing shares native application and report owners.
use super::{Arguments, ToolReply};
use crate::tools::live::LiveTools;
use ken_core::{project::ProjectPaths, tool_output::Document};
use ken_structural::application::{
    catalog::Catalog,
    search::{SearchOptions, SearchRequest, StructuralApplication, present},
    sessions::{QueryApplication, QueryOptions, SessionOptions},
};
pub(super) fn call(
    paths: &ProjectPaths,
    args: &Arguments,
    live: &mut LiveTools,
    cancellation: &ken_query::execution::Cancellation,
) -> Result<ToolReply, String> {
    let query = args
        .query
        .to_utf8()
        .ok_or("structural query contains non-scalar Unicode")?;
    if args.piece_kind != "auto" {
        return Err("piece_kind requires the default or compact files/symbols search".into());
    }
    if args.purpose != "auto" {
        return Err("purpose requires response_format=evidence or compact".into());
    }
    if !matches!(args.response_format.as_str(), "auto" | "legacy") {
        return Err("evidence responses require nonliteral scope=files or symbols".into());
    }
    let rules = args.rules.as_deref().unwrap_or_default();
    let collections = args.collections.as_deref().unwrap_or_default();
    let tags = args.tags.as_deref().unwrap_or_default();
    let files = args.rule_files.as_deref().unwrap_or_default();
    let selecting = ![rules, collections, tags, files]
        .iter()
        .all(|v| v.is_empty());
    if args.scope != "structure" && selecting {
        return Err("saved rule selectors require scope=structure".into());
    }
    let grammars = live.shared_catalog()?;
    let application =
        StructuralApplication::new(paths.root(), grammars.clone()).map_err(|e| e.to_string())?;
    let capacity = application
        .cache_capacity(args.cache_mb)
        .map_err(|e| e.to_string())?;
    if args.query_language == "kql/2" {
        if args.scope != "structure" || selecting {
            return Err("KQL2 requires a structural query; TOML migration is separate".into());
        }
        if args.evidence_mode != "strict" {
            return Err("KQL2 evidence modes are expressed by the query, not the KQL1 flag".into());
        }
        let catalog = Catalog::packaged().map_err(|e| e.to_string())?;
        let queries = QueryApplication::new(paths.root(), grammars, catalog.libraries().clone())
            .map_err(|e| e.to_string())?;
        let options = SessionOptions {
            path: args._path.clone().into(),
            cache_mb: capacity,
            ..Default::default()
        };
        let mut check = || {
            if cancellation.is_cancelled() {
                Err(
                    ken_structural::application::sessions::SessionError::Invalid(
                        "cancelled".into(),
                    ),
                )
            } else {
                Ok(())
            }
        };
        let mut session = if capacity == 0. {
            queries.open_transient_checked(options, &mut check)
        } else {
            queries.open_checked(options, &mut check)
        }
        .map_err(|e| e.to_string())?;
        let max_rows = args
            .limit
            .map(|n| {
                u64::try_from(n)
                    .ok()
                    .filter(|n| *n > 0)
                    .ok_or("limit must be positive")
            })
            .transpose()?;
        let result = session
            .search_json(
                (!query.is_empty()).then_some(query.as_str()),
                QueryOptions {
                    saved_query: args.saved_query.clone(),
                    query_name: args.query_name.clone(),
                    libraries: args.libraries.clone(),
                    timeout_ms: args.timeout_ms.map(|m| m as f64),
                    max_rows,
                    cancellation: cancellation.clone(),
                    ..Default::default()
                },
            )
            .map_err(|e| e.to_string())?;
        session.close().map_err(|e| e.to_string())?;
        let observation =
            ken_contracts::checks::Observation::parse(&result).map_err(|e| e.to_string())?;
        let report = ken_contracts::checks::query_report(&observation, args.full)
            .map_err(|e| e.to_string())?;
        return crate::tools::presentation::raw_json(
            report.json().to_owned(),
            "ken_find",
            if args.response_format == "legacy" {
                "json"
            } else {
                &args.output_format
            },
            args.full,
        );
    }
    if args.query_language != "kenql/1" {
        return Err("unsupported query_language".into());
    }
    if args.libraries.is_some() || args.saved_query.is_some() || args.query_name.is_some() {
        return Err("libraries, saved_query and query_name require query_language=kql/2".into());
    }
    if args.scope == "structure" && !rules.is_empty() {
        let store = ken_contracts::checks::Store::new(paths.root()).map_err(|e| e.to_string())?;
        let known = store
            .rules()
            .map_err(|e| e.to_string())?
            .into_iter()
            .filter_map(|record| record["definition"]["id"].as_str().map(str::to_owned))
            .collect::<std::collections::BTreeSet<_>>();
        if rules.iter().any(|id| known.contains(id)) {
            if rules.iter().any(|id| !known.contains(id))
                || !query.is_empty()
                || !collections.is_empty()
                || !tags.is_empty()
                || !files.is_empty()
            {
                return Err(
                    "search registered check rules separately from catalog selectors".into(),
                );
            }
            let max_rows = args
                .limit
                .map(|value| {
                    u64::try_from(value)
                        .ok()
                        .filter(|value| *value > 0)
                        .ok_or("limit must be positive")
                })
                .transpose()?
                .unwrap_or(100);
            let input = serde_json::json!({"rules":rules,"path":args._path,"timeout_ms":args.timeout_ms.unwrap_or(10000),"max_rows":max_rows,"full":args.full});
            let report = crate::tools::checks::application(paths, live)?
                .search_with_control(
                    &input,
                    &ken_checks_application::WorkerControl {
                        cancellation: cancellation.clone(),
                        ..Default::default()
                    },
                )
                .map_err(|e| e.to_string())?;
            return crate::tools::presentation::raw_json(
                report.json().into(),
                "ken_find",
                if args.response_format == "legacy" {
                    "json"
                } else {
                    &args.output_format
                },
                args.full,
            );
        }
    }
    let evidence_mode = match args.evidence_mode.as_str() {
        "strict" => ken_query::execution::EvidenceMode::Strict,
        "possible" => ken_query::execution::EvidenceMode::Possible,
        _ => return Err("evidence_mode must be strict or possible".into()),
    };
    let max_matches = args
        .limit
        .map(|n| {
            u64::try_from(n)
                .ok()
                .filter(|n| *n > 0)
                .ok_or("limit must be positive")
        })
        .transpose()?;
    let mut options = SearchOptions {
        path: args._path.clone().into(),
        cache_mb: Some(capacity),
        evidence_mode,
        cancellation: cancellation.clone(),
        ..Default::default()
    };
    options.budget.max_matches = max_matches;
    options.budget.timeout_ms = args.timeout_ms;
    let response = match args.scope.as_str() {
        "structure" => application.search(
            SearchRequest {
                query,
                rules: rules.to_vec(),
                collections: collections.to_vec(),
                tags: tags.to_vec(),
                rule_files: files.iter().map(Into::into).collect(),
            },
            options,
        ),
        "patterns" => application.patterns(
            &query
                .split(',')
                .map(str::trim)
                .filter(|v| !v.is_empty())
                .map(str::to_owned)
                .collect::<Vec<_>>(),
            options,
        ),
        "bugs" => application.bugs(options),
        _ => return Err("unsupported structural scope".into()),
    }
    .map_err(|e| e.to_string())?;
    let response = present(&response, &args.scope, args.full);
    let document: Document =
        Document::parse_json(&response.to_string()).map_err(|e| e.to_string())?;
    crate::tools::present(
        &document,
        "ken_find",
        if args.response_format == "legacy" {
            "json"
        } else {
            &args.output_format
        },
        args.full,
    )
}
