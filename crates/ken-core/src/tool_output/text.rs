//! Loss-aware compact projection. Field selection/ranking belongs to the caller.
use super::Document as D;
const LOCATION: &[&str] = &[
    "path",
    "file_path",
    "file",
    "line",
    "line_start",
    "start_line",
    "line_end",
    "end_line",
];
const IDENTITY: &[&str] = &["name", "qualname", "label", "kind"];
const DIAGNOSTICS: &[&str] = &[
    "score",
    "ranking_score",
    "source_hash",
    "profile_version",
    "indexed_at",
    "sha256",
    "content_hash",
    "fingerprint",
    "model_fingerprint",
    "timing",
    "elapsed_ms",
];
fn scalar(v: &D) -> String {
    match v {
        D::Null => "none".into(),
        D::Bool(v) => v.to_string(),
        D::Number(v) => v.to_string(),
        D::String(v) => v.clone(),
        _ => String::new(),
    }
}
fn start(v: &D) -> Option<i64> {
    ["start_line", "line_start", "line"]
        .iter()
        .find_map(|key| v.get(key).integer().filter(|n| *n > 0))
}
fn name(v: &D) -> Option<&str> {
    v.get("qualname")
        .string()
        .filter(|v| !v.is_empty())
        .or_else(|| v.get("name").string().filter(|v| !v.is_empty()))
}
pub fn render(value: &D, tool: &str, diagnostics: bool) -> String {
    let projected;
    let value = if tool == "ken_related"
        && !diagnostics
        && value.fields().iter().any(|(k, _)| k == "imports")
        && value.fields().iter().any(|(k, _)| k == "neighbors")
    {
        projected = compact_neighbors(value);
        &projected
    } else {
        value
    };
    let mut out = lines(value, "", diagnostics, tool == "ken_read");
    if let Some(path) = value.get("path").string()
        && out.len() > 1
        && out[0] == path
        && out[1].starts_with(&format!("{path}:"))
    {
        out.remove(0);
    }
    if out.is_empty() {
        "No results.".into()
    } else {
        out.join("\n")
    }
}
fn compact_neighbors(value: &D) -> D {
    let groups = ["imports", "imported_by", "tests", "neighbors"];
    let mut result = D::Object(
        value
            .fields()
            .iter()
            .filter(|(k, _)| !groups.contains(&k.as_str()))
            .cloned()
            .collect(),
    );
    let mut seen = std::collections::HashSet::new();
    for group in groups {
        let mut rows = Vec::new();
        for item in value.get(group).array() {
            let path = item.string().or_else(|| {
                ["path", "file", "module"]
                    .iter()
                    .find_map(|k| item.get(k).string().filter(|v| !v.is_empty()))
            });
            if let Some(path) =
                path.filter(|p| !p.is_empty() && (group != "neighbors" || !seen.contains(*p)))
            {
                rows.push(D::from(path));
                seen.insert(path.to_owned());
            }
        }
        if !rows.is_empty() {
            result.insert(group, rows);
        }
    }
    result
}
fn lines(value: &D, parent: &str, diagnostics: bool, numbered: bool) -> Vec<String> {
    match value {
        D::String(v) => {
            return if v.is_empty() {
                Vec::new()
            } else {
                v.split('\n').map(str::to_owned).collect()
            };
        }
        D::Array(v) => {
            return v
                .iter()
                .flat_map(|v| lines(v, parent, diagnostics, numbered))
                .collect();
        }
        D::Object(_) => {}
        _ => return vec![scalar(value)],
    }
    let path = ["path", "file_path", "file"]
        .iter()
        .find_map(|k| {
            value
                .fields()
                .iter()
                .find(|(field, _)| field == k)
                .map(|(_, v)| v)
        })
        .and_then(D::string)
        .unwrap_or(parent);
    let entity = value.get("entity");
    let identity = if matches!(entity, D::Object(_)) {
        entity
    } else {
        value
    };
    let mut name = name(identity).or_else(|| value.get("label").string().filter(|v| !v.is_empty()));
    let mut start = start(value);
    let mut code_key = ["code", "content", "text", "snippet"]
        .into_iter()
        .find(|key| value.get(key).string().is_some() && start.is_some());
    let symbol = value.get("symbol");
    if start.is_none() && matches!(symbol, D::Object(_)) && value.get("snippet").string().is_some()
    {
        start = self::start(symbol);
        name = self::name(symbol);
        code_key = start.map(|_| "snippet");
    }
    let mut end = value
        .fields()
        .iter()
        .find(|(k, _)| k == "end_line")
        .or_else(|| value.fields().iter().find(|(k, _)| k == "line_end"))
        .map(|(_, v)| v.clone())
        .unwrap_or_else(|| start.map_or(D::Null, D::from));
    let mut code_lines = Vec::new();
    let mut partial = false;
    if let Some(key) = code_key {
        let code = value.get(key).string().unwrap();
        if !code.is_empty() {
            code_lines = code
                .replace("\r\n", "\n")
                .split('\n')
                .map(str::to_owned)
                .collect();
        }
        if numbered
            && value.get("start_line") == &D::Null
            && let Some(first) = start
            && !code_lines.is_empty()
            && code_lines
                .iter()
                .enumerate()
                .all(|(i, line)| line.starts_with(&format!("{}: ", first + i as i64)))
        {
            for (i, line) in code_lines.iter_mut().enumerate() {
                *line = line[format!("{}: ", first + i as i64).len()..].into();
            }
        }
        if !code_lines.is_empty()
            && let Some(first) = start
        {
            let last = first + code_lines.len() as i64 - 1;
            partial = end.integer().is_some_and(|n| n > last);
            end = last.into();
        }
    }
    let mut title = if !path.is_empty() && (path != parent || start.is_some() || name.is_some()) {
        path.to_owned()
    } else {
        String::new()
    };
    if let Some(start) = start {
        title.push_str(&if let Some(end) = end.integer() {
            format!(":{start}-{end}")
        } else {
            format!(":{start}")
        });
    }
    if let Some(name) = name {
        if !title.is_empty() {
            title.push_str(" :: ");
        }
        title.push_str(name);
    }
    if identity.get("kind").truthy() && !title.is_empty() {
        title.push_str(&format!(" ({})", scalar(identity.get("kind"))));
    }
    let mut flags: Vec<&str> = ["stale", "truncated"]
        .into_iter()
        .filter(|key| value.get(key).truthy())
        .collect();
    if partial {
        flags.push("partial");
    }
    if !flags.is_empty() {
        title.push_str(&format!(" [{}]", flags.join(", ")));
    }
    let titled = !title.is_empty();
    let mut out = if titled { vec![title] } else { Vec::new() };
    if matches!(entity, D::Object(_)) {
        let extra = D::Object(
            entity
                .fields()
                .iter()
                .filter(|(k, _)| !LOCATION.contains(&k.as_str()) && !IDENTITY.contains(&k.as_str()))
                .cloned()
                .collect(),
        );
        if extra.truthy() {
            out.extend(lines(&extra, path, diagnostics, numbered));
        }
    }
    if code_key.is_some()
        && let Some(first) = start
    {
        out.extend(
            code_lines
                .iter()
                .enumerate()
                .map(|(i, line)| format!("{} | {line}", first + i as i64)),
        );
    }
    for (key, item) in value.fields() {
        let key = key.as_str();
        let consumed = if titled {
            LOCATION.contains(&key) || IDENTITY.contains(&key)
        } else {
            LOCATION.contains(&key) && item.string() == Some(parent)
        };
        if consumed
            || code_key == Some(key)
            || (key == "entity" && matches!(entity, D::Object(_)))
            || (!diagnostics && DIAGNOSTICS.contains(&key))
            || (key == "ok" && item == &D::Bool(true))
            || flags.contains(&key)
        {
            continue;
        }
        if item == &D::Null
            && [
                "status", "complete", "coverage", "validity", "resolved", "matched", "passed",
            ]
            .contains(&key)
        {
            out.push(format!("{key}: none"));
            continue;
        }
        if item.is_empty() {
            if ["results", "matches", "findings", "snippets", "candidates"].contains(&key) {
                out.push(format!("{key}: none"));
            }
            continue;
        }
        if matches!(item, D::Array(_) | D::Object(_)) {
            let children = lines(item, path, diagnostics, numbered);
            if !children.is_empty() {
                if [
                    "results", "outline", "source", "symbols", "symbol", "snippets", "evidence",
                ]
                .contains(&key)
                {
                    out.extend(children);
                } else {
                    out.push(format!("{key}:"));
                    out.extend(children.into_iter().map(|s| format!("  {s}")));
                }
            }
        } else {
            let text = scalar(item);
            if text.contains('\n') {
                out.push(format!("{key}:"));
                out.extend(text.split('\n').map(str::to_owned));
            } else {
                out.push(format!("{key}: {text}"));
            }
        }
    }
    out
}
