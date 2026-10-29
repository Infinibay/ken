//! One lazy grammar owner for all public live-syntax tools, independent of models.
use ken_core::tool_output::Document;
use ken_search::{
    SearchInstallation,
    navigation::{CallGraphRequest, IndexNavigation},
};
use ken_syntax::GrammarCatalog;
use std::path::PathBuf;

pub(super) struct LiveTools {
    installation: PathBuf,
    grammars: Option<GrammarCatalog>,
}
impl LiveTools {
    pub(super) fn new(installation: PathBuf) -> Self {
        Self {
            installation,
            grammars: None,
        }
    }
    fn catalog(&mut self) -> Result<&GrammarCatalog, String> {
        if self.grammars.is_none() {
            self.grammars = Some(
                SearchInstallation::open_grammars(&self.installation).map_err(|e| e.to_string())?,
            );
        }
        Ok(self.grammars.as_ref().unwrap())
    }
    pub(super) fn related(
        &mut self,
        nav: &IndexNavigation,
        target: &str,
        relation: &str,
        confidence: f64,
        limit: i64,
    ) -> Result<Document, String> {
        let catalog = self.catalog()?;
        match relation {
            "callers" | "callees" => nav.callgraph(
                catalog,
                &CallGraphRequest {
                    qualname: target.into(),
                    direction: relation.into(),
                    min_confidence: confidence.into(),
                    limit,
                    ..Default::default()
                },
            ),
            // Preserve the original public adapter's down/up vs sub/super mismatch.
            "subtypes" | "supertypes" => nav.type_hierarchy(
                catalog,
                target,
                if relation == "subtypes" { "down" } else { "up" },
                true,
            ),
            _ => unreachable!("live relation selected by shared tool boundary"),
        }
        .map_err(|e| e.to_string())
    }
    pub(super) fn wiring(
        &mut self,
        nav: &IndexNavigation,
        query: &str,
        limit: i64,
    ) -> Result<Document, String> {
        nav.wiring(self.catalog()?, query, "", limit)
            .map_err(|e| e.to_string())
    }
}
