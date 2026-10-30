use super::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
#[derive(Default)]
pub struct SavedRule {
    pub id: String,
    pub query: String,
    pub name: String,
    pub description: String,
    pub tags: Vec<String>,
    pub collections: Vec<String>,
    pub severity: Option<String>,
    pub recommendation: String,
    pub caveat: String,
    pub variants: Vec<Value>,
    pub source: String,
    pub operations: Vec<Value>,
    pub query_language: String,
}
fn word(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-')
}
pub(super) fn valid_id(id: &str) -> bool {
    let Some(first) = id.chars().next() else {
        return false;
    };
    first.is_ascii_alphanumeric() && {
        let mut parts = id.split('#');
        parts.next().is_some_and(|p| p.chars().all(word))
            && parts
                .next()
                .is_none_or(|p| !p.is_empty() && p.chars().all(word))
            && parts.next().is_none()
    }
}
impl SavedRule {
    pub(super) fn validate(
        &self,
        compiled: &mut super::compilation::Compilation<'_>,
    ) -> Result<()> {
        if !["", "kenql/1", "kql/2"].contains(&self.query_language.as_str()) {
            return Err(invalid("unsupported query_language"));
        }
        if !valid_id(&self.id) {
            return Err(invalid(
                "rule id must contain only letters, numbers, dots, underscores or hyphens",
            ));
        }
        if self.query_language == "kql/2"
            && !self.query.trim_start().starts_with("language \"kql/2\"")
        {
            return Err(invalid("KQL 2 rule requires its language header"));
        }
        if self
            .tags
            .iter()
            .chain(&self.collections)
            .any(|s| s.trim().is_empty())
        {
            return Err(invalid(format!(
                "rule {}: tags and collections must contain nonempty strings",
                self.id
            )));
        }
        let mut variants = BTreeSet::new();
        for variant in &self.variants {
            let id = variant["id"].as_str().unwrap_or("");
            if !variant.is_object()
                || id.is_empty()
                || !id.chars().all(word)
                || !variants.insert(id)
            {
                return Err(invalid("invalid or duplicate variant id"));
            }
            if variant["status"] == "ready" {
                compiled.query(
                    variant["query"]
                        .as_str()
                        .ok_or_else(|| invalid("ready variant requires a query"))?,
                )?;
            }
        }
        let mut operations = BTreeSet::new();
        for operation in &self.operations {
            let Some(fields) = operation.as_object() else {
                return Err(invalid("invalid operation fields"));
            };
            if fields.iter().any(|(k, v)| {
                !["id", "status", "query", "description", "caveat"].contains(&k.as_str())
                    || !v.is_string()
            }) {
                return Err(invalid("invalid operation fields"));
            }
            let id = operation["id"].as_str().unwrap_or("");
            if !id
                .chars()
                .next()
                .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
                || !id.chars().all(|c| ken_text::unicode::word(c) || c == '-')
                || !operations.insert(id)
            {
                return Err(invalid("invalid or duplicate operation id"));
            }
            if !matches!(operation["status"].as_str(), Some("ready" | "design")) {
                return Err(invalid("operation status must be ready or design"));
            }
            if operation["status"] == "ready" {
                compiled.query(operation["query"].as_str().unwrap_or(""))?;
            }
        }
        compiled.query(&self.query)?;
        Ok(())
    }
}
