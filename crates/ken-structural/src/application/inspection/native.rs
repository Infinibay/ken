//! Thin bridge to the one native query application. It owns no linker/runtime.
use super::{
    InspectRequest, InspectionQueries, NativeSources, ObservationRequest, Result, inspect_with,
    invalid,
};
use crate::application::sessions::{QueryApplication, QueryOptions, SessionError, SessionOptions};
use ken_syntax::GrammarCatalog;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path, sync::Arc, time::Instant};
pub struct SessionQueries {
    application: QueryApplication,
    identity: String,
}
impl SessionQueries {
    pub fn new(
        root: &Path,
        catalog: Arc<GrammarCatalog>,
        packaged: BTreeMap<String, String>,
    ) -> Result<Self> {
        let mut identity = Sha256::new();
        identity.update(crate::IMPLEMENTATION_FINGERPRINT.as_bytes());
        identity.update([0]);
        identity.update(serde_json::to_vec(&packaged)?);
        let identity = format!("{:x}", identity.finalize());
        let application =
            QueryApplication::new(root, catalog, packaged).map_err(|e| invalid(e.to_string()))?;
        Ok(Self {
            application,
            identity,
        })
    }
}
impl InspectionQueries for SessionQueries {
    fn identity(&self) -> String {
        self.identity.clone()
    }
    fn observe(&mut self, request: &ObservationRequest) -> Result<Value> {
        let mut check = || {
            if Instant::now() >= request.deadline {
                Err(SessionError::Execution(
                    ken_query::execution::ExecutionError::Exhausted("timeout_ms"),
                ))
            } else {
                Ok(())
            }
        };
        let mut session = self
            .application
            .open_checked(
                SessionOptions {
                    path: request.scope.clone().into(),
                    source_paths: Some(request.paths.clone()),
                    ..Default::default()
                },
                &mut check,
            )
            .map_err(|e| invalid(e.to_string()))?;
        let result = (|| {
            let response = session
                .search(
                    Some(&request.query),
                    QueryOptions {
                        timeout_ms: Some(request.timeout_ms),
                        deadline: Some(request.deadline),
                        max_rows: Some(request.max_rows as u64),
                        max_states: Some(200000),
                        include_entities: true,
                        ..Default::default()
                    },
                )
                .map_err(|e| invalid(e.to_string()))?;
            response.to_json().map_err(|e| invalid(e.to_string()))
        })();
        let closed = session.close().map_err(|e| invalid(e.to_string()));
        match result {
            Ok(value) => {
                closed?;
                Ok(value)
            }
            Err(error) => Err(error),
        }
    }
}
pub fn inspect_native(
    root: &Path,
    request: &InspectRequest,
    catalog: Arc<GrammarCatalog>,
    packaged: BTreeMap<String, String>,
) -> Result<Value> {
    let mut queries = SessionQueries::new(root, catalog.clone(), packaged)?;
    let mut sources = NativeSources::new(catalog);
    inspect_with(root, request, &mut queries, &mut sources)
}
