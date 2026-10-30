use super::{Program, SourceFacts, location, qualname};
use serde_json::{Value, json};
use std::collections::BTreeSet;
pub fn describe(program: &Program, seeds: &[String], context: &SourceFacts) -> Value {
    if !context.path.ends_with(".py") {
        return json!({"status":"unknown","context":context.path,"candidates":[],"reason":"Contextual access expressions are currently modeled for Python; no cross-language visibility claim."});
    }
    if !context.issues.is_empty() {
        return json!({"status":"unknown","context":context.path,"candidates":[],"reason":context.issues.iter().map(|v|v["reason"].as_str().unwrap_or("source syntax unavailable")).collect::<Vec<_>>().join("; ")});
    }
    let paths = program
        .snapshot
        .as_ref()
        .and_then(|s| s["manifest"].as_array())
        .into_iter()
        .flatten()
        .filter_map(|p| p[0].as_str())
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    let mut candidates = Vec::new();
    let mut issues = BTreeSet::new();
    for key in seeds {
        let Some(node) = program.nodes.get(key) else {
            continue;
        };
        let name = qualname(node);
        if name.contains('.') {
            issues.insert("Methods require an instance/type and initialization analysis.");
            continue;
        }
        let mut expressions = Vec::new();
        if node["path"] == context.path {
            expressions.push(json!({"expression":name,"basis":"same_module_declaration"}));
        }
        for import in context.imports.iter().filter(|i| i.top_level) {
            if import.kind == "from" {
                let found =
                    ken_program::python_module_targets(&context.path, &import.module, &paths);
                if found.len() == 1 && node["path"] == found[0] {
                    for alias in import.aliases.iter().filter(|a| a.name == name) {
                        expressions.push(json!({"expression":alias.asname.as_deref().unwrap_or(&alias.name),"basis":"explicit_from_import","line":import.line}));
                    }
                }
            } else {
                for alias in &import.aliases {
                    let found =
                        ken_program::python_module_targets(&context.path, &alias.name, &paths);
                    if found.len() == 1 && node["path"] == found[0] {
                        expressions.push(json!({"expression":format!("{}.{}",alias.asname.as_deref().unwrap_or(&alias.name),name),"basis":"explicit_module_import","line":import.line}));
                    }
                }
            }
        }
        for expression in expressions {
            let mut candidate = expression;
            candidate["target"] = location(node);
            candidate["status"] = json!("candidate");
            candidate["obligations"] = json!([
                "binding not shadowed at the use site",
                "module initialization completed",
                "argument and return type compatibility",
                "effects and errors preserved"
            ]);
            candidates.push(candidate);
        }
    }
    json!({"status":if candidates.is_empty(){"unknown"}else{"candidates"},"context":context.path,"candidates":candidates,"issues":issues,"claim":"Explicit access spellings only; absence does not prove unavailability. No replacement or autofix is certified."})
}
