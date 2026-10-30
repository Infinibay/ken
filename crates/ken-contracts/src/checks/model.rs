use super::{Result, invalid, wire};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
pub fn digest(value: &Value) -> String {
    ken_knowledge::reasoning::digest(value)
}
pub fn relative(value: &str) -> Result<String> {
    if value.is_empty() || value.contains('\\') {
        return Err(invalid("scope must be a project-relative POSIX path"));
    }
    if value.starts_with('/') {
        return Err(invalid("scope must stay inside project source"));
    }
    let parts = value
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .collect::<Vec<_>>();
    if parts.iter().any(|p| ["..", ".ken", ".git"].contains(p)) {
        return Err(invalid("scope must stay inside project source"));
    }
    Ok(if parts.is_empty() {
        ".".into()
    } else {
        parts.join("/")
    })
}
fn dot() -> String {
    ".".into()
}
fn expectation() -> String {
    "no_matches".into()
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rule {
    pub id: String,
    pub query: String,
    pub description: String,
    #[serde(default = "dot")]
    pub path: String,
    #[serde(default = "expectation")]
    pub expectation: String,
    #[serde(default)]
    pub examples: Vec<Value>,
    #[serde(default)]
    pub libraries: BTreeMap<String, String>,
}
pub(super) fn valid_id(value: &str) -> bool {
    let b = value.as_bytes();
    !b.is_empty()
        && b.len() <= 100
        && b[0].is_ascii_alphanumeric()
        && b.iter()
            .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(c))
}
impl Rule {
    pub fn read(data: &Value) -> Result<Self> {
        let rule: Self =
            serde_json::from_value(data.clone()).map_err(|_| invalid("invalid rule fields"))?;
        if !valid_id(&rule.id) {
            return Err(invalid("invalid rule id"));
        }
        if !rule.query.trim_start().starts_with("language \"kql/2\";")
            || rule.query.chars().count() > 100000
        {
            return Err(invalid(
                "a versioned KQL2 query of at most 100000 characters is required",
            ));
        }
        if rule.description.trim().is_empty() || rule.description.chars().count() > 2000 {
            return Err(invalid("description must contain 1..2000 characters"));
        }
        if relative(&rule.path)? != rule.path {
            return Err(invalid("use a normalized scope path"));
        }
        if !["no_matches", "some_match"].contains(&rule.expectation.as_str()) {
            return Err(invalid("expectation must be no_matches or some_match"));
        }
        if rule.libraries.len() > 16 || rule.libraries.values().any(|v| v.chars().count() > 100000)
        {
            return Err(invalid(
                "libraries must map module names to bounded KQL source",
            ));
        }
        if rule.examples.len() > 12 {
            return Err(invalid("at most 12 examples are accepted"));
        }
        for case in &rule.examples {
            let Some(case) = case.as_object().filter(|c| {
                c.len() == 3
                    && ["name", "files", "expect"]
                        .iter()
                        .all(|k| c.contains_key(*k))
            }) else {
                return Err(invalid("examples require name, files and expect"));
            };
            let name = case["name"]
                .as_str()
                .ok_or_else(|| invalid("example name must contain 1..100 characters"))?;
            if !(1..=100).contains(&name.chars().count()) {
                return Err(invalid("example name must contain 1..100 characters"));
            }
            if !case["expect"]
                .as_str()
                .is_some_and(|v| ["pass", "fail", "unknown"].contains(&v))
            {
                return Err(invalid("example expect must be pass, fail or unknown"));
            }
            let files = case["files"]
                .as_object()
                .filter(|m| (1..=20).contains(&m.len()))
                .ok_or_else(|| invalid("examples require 1..20 source files"))?;
            for (path, source) in files {
                if relative(path)? == "."
                    || source.as_str().is_none_or(|s| s.chars().count() > 100000)
                {
                    return Err(invalid("invalid example source"));
                }
            }
        }
        if wire::ascii_size(&rule.data()) > 1000000 {
            return Err(invalid("rule and examples exceed 1 MB"));
        }
        Ok(rule)
    }
    pub fn data(&self) -> Value {
        serde_json::to_value(self).unwrap()
    }
    pub fn revision(&self) -> String {
        digest(&self.data())
    }
}
/// Missing admission metadata cannot certify either polarity.
pub fn judgment(result: &Value, expectation: &str) -> String {
    super::Observation::from_json(result)
        .map(|result| super::judgment_observation(&result, expectation))
        .unwrap_or_else(|_| "unknown".into())
}
