use super::index::Context;
use crate::{ProgramError, StructuralIr, attributes};
use ruff_python_ast::{self as py, Stmt};
use ruff_python_parser::{Mode, ParseErrorType, ParseOptions, parse_unchecked};
use serde::Deserialize;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
};
use unicode_normalization::UnicodeNormalization;
#[derive(Deserialize)]
struct Exception {
    canonical: String,
    ancestors: Vec<String>,
}
#[derive(Deserialize)]
struct Builtins {
    exceptions: BTreeMap<String, Exception>,
}
fn builtins() -> &'static BTreeMap<String, Exception> {
    static DATA: OnceLock<Builtins> = OnceLock::new();
    &DATA
        .get_or_init(|| {
            serde_json::from_str(include_str!("../../resources/python-exceptions.json"))
                .expect("frozen Python exception hierarchy")
        })
        .exceptions
}
fn imports(source: &str) -> Option<Vec<String>> {
    let parsed = parse_unchecked(
        source,
        ParseOptions::from(Mode::Module).with_target_version(py::PythonVersion::PY312),
    );
    if parsed
        .errors()
        .iter()
        .any(|e| !matches!(e.error, ParseErrorType::DuplicateKeywordArgumentError(_)))
        || !parsed.unsupported_syntax_errors().is_empty()
    {
        return None;
    }
    let py::Mod::Module(module) = parsed.into_syntax() else {
        return None;
    };
    let stmt = module.body.first()?;
    let names = match stmt {
        Stmt::Import(import) => import
            .names
            .iter()
            .map(|a| {
                a.asname.as_ref().map_or_else(
                    || a.name.as_str().split('.').next().unwrap().to_owned(),
                    |a| a.as_str().into(),
                )
            })
            .collect::<Vec<_>>(),
        Stmt::ImportFrom(import) => import
            .names
            .iter()
            .map(|a| a.asname.as_ref().unwrap_or(&a.name).as_str().to_owned())
            .collect(),
        _ => Vec::new(),
    };
    Some(names.into_iter().map(|s| s.nfkc().collect()).collect())
}
pub(super) fn shadowed(
    graph: &StructuralIr,
) -> Result<BTreeMap<String, BTreeSet<String>>, ProgramError> {
    let entities = graph
        .entities
        .iter()
        .map(|(id, e)| (id.as_str(), e))
        .collect::<BTreeMap<_, _>>();
    let mut result = BTreeMap::<String, BTreeSet<String>>::new();
    for fact in &graph.facts {
        if ["DECLARES", "HAS_PARAMETER"].contains(&fact.relation.as_str())
            && let Some(e) = entities.get(fact.object.as_str())
        {
            result
                .entry(fact.subject.clone())
                .or_default()
                .insert(e.name.clone());
        }
        if fact.relation == "IMPORT_SYNTAX"
            && attributes::get(&fact.attrs, "language")?.is_some_and(|v| v == "python")
        {
            result
                .entry(fact.subject.clone())
                .or_default()
                .extend(imports(&fact.object).unwrap_or_else(|| vec!["*".into()]));
        }
    }
    Ok(result)
}
pub(super) fn handler_types(
    ctx: &Context<'_>,
    arm: usize,
    bound: &BTreeSet<String>,
    shadowed: &BTreeSet<String>,
) -> Result<Option<Vec<String>>, ProgramError> {
    let mut todo = ctx
        .kids(arm)
        .iter()
        .filter(|&&i| ctx.op(i).role == "value" || ctx.op(i).native_kind == "as_pattern")
        .copied()
        .collect::<Vec<_>>();
    if todo.is_empty() {
        return Ok(Some(vec!["BaseException".into()]));
    }
    let mut names = BTreeSet::new();
    let mut visited = BTreeSet::new();
    while let Some(i) = todo.pop() {
        if !visited.insert(i) {
            return Ok(None);
        }
        let op = ctx.op(i);
        if op.role == "alias" {
            continue;
        }
        if op.native_kind == "identifier" {
            let name = attributes::text(&op.attrs, "text", "")?;
            if bound.contains(&op.id)
                || shadowed.contains(&name)
                || shadowed.contains("*")
                || !builtins().contains_key(&name)
            {
                return Ok(None);
            }
            names.insert(name);
        } else if !["tuple", "as_pattern", "parenthesized_expression"]
            .contains(&op.native_kind.as_str())
        {
            return Ok(None);
        }
        todo.extend(ctx.kids(i));
    }
    Ok((!names.is_empty()).then(|| names.into_iter().collect()))
}
pub(super) fn catches_close(types: Option<&[String]>) -> &'static str {
    let Some(types) = types else {
        return "unknown";
    };
    if types.iter().any(|name| {
        let b = builtins();
        b.get(name)
            .is_some_and(|parent| b["GeneratorExit"].ancestors.contains(&parent.canonical))
    }) {
        "yes"
    } else {
        "no"
    }
}
