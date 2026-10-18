//! Authenticated loopback health; no daemon lifecycle operations.
use crate::{
    project::ProjectPaths,
    status::{HealthProbe, StatusError},
};
use serde_json::{Map, Value};
use std::{fs, time::Duration};

pub struct DaemonHealthClient {
    agent: ureq::Agent,
}
impl Default for DaemonHealthClient {
    fn default() -> Self {
        Self::new()
    }
}
impl DaemonHealthClient {
    pub fn new() -> Self {
        Self {
            agent: ureq::Agent::config_builder()
                .proxy(None)
                .max_redirects(0)
                .timeout_global(Some(Duration::from_secs(1)))
                .build()
                .into(),
        }
    }
}
impl HealthProbe for DaemonHealthClient {
    fn probe(
        &self,
        paths: &ProjectPaths,
        metadata: &Map<String, Value>,
    ) -> Result<Option<Map<String, Value>>, StatusError> {
        let Some(port) = fs::read_to_string(paths.port())
            .ok()
            .and_then(|s| s.trim().parse::<u16>().ok())
            .filter(|p| *p > 0)
        else {
            return Ok(None);
        };
        let token = metadata
            .get("auth_token")
            .and_then(Value::as_str)
            .ok_or_else(|| StatusError::Metadata {
                path: paths.meta(),
                reason: "auth_token must be a string",
            })?;
        let Ok(mut response) = self
            .agent
            .get(format!("http://127.0.0.1:{port}/health"))
            .header("Authorization", format!("Bearer {token}"))
            .call()
        else {
            return Ok(None);
        };
        if !response.status().is_success() {
            return Ok(None);
        }
        let Some(value) = response
            .body_mut()
            .read_to_string()
            .ok()
            .and_then(|body| serde_json::from_str::<Value>(&body).ok())
        else {
            return Ok(None);
        };
        Ok(match value {
            Value::Object(map) if !map.is_empty() => Some(map),
            _ => None,
        })
    }
}
