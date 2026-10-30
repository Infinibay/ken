use super::{Program, location, qualname};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub fn describe(program: &Program, seeds: &[String], depth: usize, limit: usize) -> Value {
    let connected = program.connected(seeds, depth);
    let seed_set = seeds.iter().cloned().collect::<BTreeSet<_>>();
    let mut ordered = Vec::new();
    let mut seen = BTreeSet::new();
    for id in seeds.iter().chain(connected.difference(&seed_set)) {
        if seen.insert(id.clone()) {
            ordered.push(id.clone());
        }
    }
    let ids = ordered
        .iter()
        .take(limit)
        .enumerate()
        .map(|(i, k)| (k.clone(), i))
        .collect::<BTreeMap<_, _>>();
    let mut nodes = Vec::new();
    for id in ordered.iter().take(limit) {
        let Some(node) = program.nodes.get(id) else {
            continue;
        };
        let outgoing = program
            .calls
            .iter()
            .filter(|c| &c.owner == id)
            .collect::<Vec<_>>();
        let incoming = program.calls.iter().any(|c| c.targets.contains(id));
        let resolved = outgoing.iter().any(|c| c.resolution == "resolved");
        let mut roles = Vec::new();
        if !incoming && !outgoing.is_empty() {
            roles.push(json!({"role":"entry_candidate","basis":"No incoming calls observed in this scope."}));
        }
        if outgoing.len() > 1 {
            roles.push(
                json!({"role":"coordinator_candidate","basis":"Invokes multiple operations."}),
            );
        }
        if resolved {
            roles.push(json!({"role":"delegates","basis":"Calls a resolved project callable."}));
        } else {
            roles.push(json!({"role":"executor_candidate","basis":"End of the observed project-call chain; external effects remain unverified."}));
        }
        let mut item = location(node);
        item["symbol"] = json!(qualname(node));
        item["id"] = json!(ids[id]);
        item["roles"] = json!(roles);
        item["inference"] = json!("structural_hypothesis");
        nodes.push(item);
    }
    let mut calls = Vec::new();
    for call in &program.calls {
        let Some(from) = ids.get(&call.owner) else {
            continue;
        };
        let destinations = call
            .targets
            .iter()
            .filter_map(|t| ids.get(t))
            .collect::<Vec<_>>();
        if !destinations.is_empty() || call.targets.is_empty() {
            calls.push(json!({"from":from,"to":destinations,"call":location(&call.site),"resolution":call.resolution}));
        }
    }
    let truncated = ordered.len() > limit || calls.len() > limit * 3;
    calls.truncate(limit * 3);
    json!({"scope":program.scope,"nodes":nodes,"calls":calls,"truncated":truncated,"coverage":program.coverage(),"claim":"Roles are hypotheses from observed calls, not proof of business responsibility or public visibility."})
}
