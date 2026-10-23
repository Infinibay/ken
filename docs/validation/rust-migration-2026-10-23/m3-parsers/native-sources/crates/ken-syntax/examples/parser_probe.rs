//! Bounded external consumer; requests contain inputs only, never expectations.
use ken_syntax::{GrammarCatalog, Language, ParserRegistry};
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::BTreeSet,
    io::{self, Read},
    path::PathBuf,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    manifest: PathBuf,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    language: Language,
    hint: String,
    source_hex: String,
}
fn main() -> Result<(), String> {
    let mut input = Vec::new();
    io::stdin()
        .take(16 * 1024 * 1024 + 1)
        .read_to_end(&mut input)
        .map_err(|e| e.to_string())?;
    if input.len() > 16 * 1024 * 1024 {
        return Err("parser request exceeds16MiB".into());
    }
    let request: Request = serde_json::from_slice(&input).map_err(|e| e.to_string())?;
    if !request.manifest.is_absolute() || request.cases.is_empty() || request.cases.len() > 4096 {
        return Err("absolute manifest and1..4096cases required".into());
    }
    let catalog = GrammarCatalog::prepared(&request.manifest).map_err(|e| e.to_string())?;
    let parsers = ParserRegistry::new(
        GrammarCatalog::prepared(&request.manifest).map_err(|e| e.to_string())?,
    );
    let mut ids = BTreeSet::new();
    let mut rows = Vec::new();
    let mut budget = 0;
    for case in request.cases {
        if case.id.is_empty() || !ids.insert(case.id.clone()) {
            return Err("unique nonempty case identities required".into());
        }
        let hex = case.source_hex.as_bytes();
        if !hex.len().is_multiple_of(2) || !hex.iter().all(u8::is_ascii_hexdigit) {
            return Err("strict hexadecimal source required".into());
        }
        let source = hex
            .chunks_exact(2)
            .map(|p| {
                fn digit(c: u8) -> u8 {
                    if c.is_ascii_digit() {
                        c - b'0'
                    } else {
                        c.to_ascii_lowercase() - b'a' + 10
                    }
                }
                digit(p[0]) * 16 + digit(p[1])
            })
            .collect::<Vec<_>>();
        let row = match parsers.parse(case.language, &source, &case.hint) {
            Ok(parsed) => {
                let tree = catalog
                    .syntax(case.language, &source, &case.hint)
                    .map_err(|e| e.to_string())?;
                json!({"id":case.id,"parsed":parsed,"syntax":tree.snapshot()})
            }
            Err(error) => json!({"id":case.id,"error":error.to_string()}),
        };
        budget += serde_json::to_vec(&row).map_err(|e| e.to_string())?.len();
        if budget > 32 * 1024 * 1024 - 4096 {
            return Err("parser response exceeds32MiB".into());
        }
        rows.push(row);
    }
    println!(
        "{}",
        json!({"format":"ken-parser-observation/1","cases":rows})
    );
    Ok(())
}
