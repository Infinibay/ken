use super::{Call, Program, location, qualname};
use serde_json::{Value, json};
use std::collections::BTreeSet;
fn span(value: &str) -> Option<(&str, &str)> {
    let value = value.strip_suffix(":call").unwrap_or(value);
    let tail = value
        .rsplit_once("::op:")
        .map(|(_, tail)| tail)
        .or_else(|| value.rsplit_once('@').map(|(_, tail)| tail))?;
    let (a, b) = tail.split_once(':')?;
    (!a.is_empty()
        && !b.is_empty()
        && a.bytes().all(|c| c.is_ascii_digit())
        && b.bytes().all(|c| c.is_ascii_digit()))
    .then_some((a, b))
}
pub fn result_uses<'a>(program: &'a Program, call: &Call, target: &str) -> Vec<&'a Value> {
    let occurrence = call.site["local_id"].as_str().and_then(span);
    program
        .uses
        .iter()
        .filter(|u| {
            u.owner == call.owner
                && u.target == target
                && occurrence.is_some()
                && span(&u.site) == occurrence
        })
        .map(|u| &u.usage)
        .collect()
}
fn is_test(path: &str, symbol: &str) -> bool {
    let name = path.rsplit('/').next().unwrap_or("");
    path.split('/')
        .any(|p| ["test", "tests", "__tests__"].contains(&p))
        || name.starts_with("test_")
        || name.contains(".test.")
        || name.contains(".spec.")
        || symbol.rsplit('.').next().unwrap_or("").starts_with("test_")
}
fn use_view(use_: &Value) -> Value {
    let mut output = serde_json::Map::new();
    for key in ["kind", "path", "line", "position"] {
        if let Some(value) = use_.get(key).filter(|v| !v.is_null()) {
            output.insert(key.into(), value.clone());
        }
    }
    Value::Object(output)
}
fn explain(program: &Program, uses: &[&Value], resolved: bool, hop: usize, depth: usize) -> Value {
    let mut boundaries = Vec::new();
    for use_ in uses {
        let kind = use_["kind"].as_str().unwrap_or("");
        if kind == "assignment" {
            continue;
        }
        let mut boundary = use_view(use_);
        match kind {
            "return" => {
                boundary["status"] = json!("returned_identity");
                boundary["next"] = json!("Inspect callers and their ownership contract.");
                boundary["followed"] = json!(resolved && hop < depth);
                if hop >= depth {
                    boundary["stop_reason"] = json!("depth_limit");
                } else if !resolved {
                    boundary["stop_reason"] = json!("ambiguous_target");
                }
            }
            "argument" | "receiver" => {
                if let Some(call) = program
                    .calls
                    .iter()
                    .find(|c| c.site["local_id"] == use_["consumer"])
                {
                    boundary["consumer"] = location(&call.site);
                    boundary["resolution"] = json!(call.resolution);
                    boundary["targets"] = json!(
                        call.targets
                            .iter()
                            .filter_map(|t| program.nodes.get(t))
                            .map(location)
                            .collect::<Vec<_>>()
                    );
                } else if super::truth(&use_["consumer_name"]) {
                    boundary["consumer"] = json!({"path":use_["path"],"line":use_["line"],"name":use_["consumer_name"],"kind":"CALL"});
                    boundary["resolution"] = json!("not_inspected");
                }
                boundary["status"] = json!(if kind == "argument" {
                    "argument_boundary"
                } else {
                    "receiver_use"
                });
                boundary["next"] = json!(
                    "Read the receiving method's contract and failure paths; ownership is not established by this use."
                );
                if kind == "receiver"
                    && boundary["consumer"]["name"]
                        .as_str()
                        .is_some_and(|s| ["close", "dispose", "release"].contains(&s))
                {
                    boundary["status"] = json!("cleanup_candidate");
                    boundary["next"] = json!(
                        "Verify this method releases the resource and runs on all required paths."
                    );
                }
            }
            "operand" => {
                boundary["status"] = json!("transformed_value");
                boundary["next"] = json!(
                    "Inspect the transformation; the derived result has a different identity."
                );
            }
            _ => {
                boundary["status"] = json!("local_use");
                boundary["next"] = json!("Inspect this condition and the paths that follow it.");
            }
        }
        boundaries.push(boundary);
    }
    let mut output = json!({"identity":if uses.is_empty(){"unknown"}else{"observed"},"boundaries":boundaries,"ownership":"unproven","inventory":"open"});
    if boundaries.is_empty() {
        output["next"] = json!(
            "Inspect the call's enclosing statement; no observed use does not prove discard or a leak."
        );
    }
    output
}
pub fn analyze(program: &Program, seeds: &[String], depth: usize, limit: usize) -> Value {
    let mut frontier = seeds.iter().cloned().collect::<BTreeSet<_>>();
    let mut visited = frontier.clone();
    let (mut consumers, mut tests, mut unresolved) = (Vec::new(), Vec::new(), Vec::new());
    let mut seen_calls = BTreeSet::new();
    for hop in 1..=depth {
        let mut following = BTreeSet::new();
        for call in &program.calls {
            let affected = call
                .targets
                .iter()
                .filter(|t| frontier.contains(*t))
                .cloned()
                .collect::<BTreeSet<_>>();
            if affected.is_empty() {
                continue;
            }
            let site_id = call.site["local_id"].as_str().unwrap_or("");
            if !seen_calls.insert(site_id.to_owned()) {
                continue;
            }
            let Some(owner) = program.nodes.get(&call.owner) else {
                continue;
            };
            let uses = affected
                .iter()
                .flat_map(|target| result_uses(program, call, target))
                .collect::<Vec<_>>();
            let mut caller = location(owner);
            caller["symbol"] = json!(qualname(owner));
            let mut item = json!({"caller":caller,"call":location(&call.site),"resolution":call.resolution,"result_uses":uses.iter().map(|u|use_view(u)).collect::<Vec<_>>(),"hops":hop,"result_flow":explain(program,&uses,call.resolution=="resolved",hop,depth),"via":affected.iter().filter_map(|t|program.nodes.get(t)).map(location).collect::<Vec<_>>()});
            if uses.is_empty() {
                item["usage_status"] = json!("unknown");
            }
            if is_test(owner["path"].as_str().unwrap_or(""), &qualname(owner)) {
                tests.push(item.clone());
            }
            consumers.push(item);
            if call.resolution == "resolved" && uses.iter().any(|u| u["kind"] == "return") {
                following.insert(call.owner.clone());
            }
        }
        frontier = following.difference(&visited).cloned().collect();
        visited.extend(following);
    }
    let names = seeds
        .iter()
        .filter_map(|s| program.nodes.get(s))
        .filter_map(|n| n["name"].as_str())
        .collect::<BTreeSet<_>>();
    for call in &program.calls {
        if call.resolution != "resolved"
            && call.site["name"]
                .as_str()
                .is_some_and(|n| names.contains(n))
        {
            let mut item = location(&call.site);
            item["resolution"] = json!(call.resolution);
            item["claim"] = json!("Spelling match only; not an established dependency.");
            unresolved.push(item);
        }
    }
    let truncated = consumers.len().max(tests.len()).max(unresolved.len()) > limit;
    consumers.truncate(limit);
    tests.truncate(limit);
    unresolved.truncate(limit);
    json!({"scope":program.scope,"targets":seeds.iter().filter_map(|s|program.nodes.get(s)).map(location).collect::<Vec<_>>(),"consumers":consumers,"tests":tests,"unresolved_candidates":unresolved,"truncated":truncated,"depth":depth,"coverage":program.coverage(),"claim":"Observed result consumers and return propagation. Test links show use, not assertion coverage; empty uses are not proof of discard."})
}
