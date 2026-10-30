//! Pure core coordination. Library discovery/caching belong to the host layer.
use crate::{
    Result,
    ast::File,
    expression_check::wrapped,
    relational::{CompiledQuery, compile_relational, has_graph},
};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BackendPreference {
    #[default]
    Automatic,
    Relational,
}
/// Compile a source module with an explicit immutable library snapshot.
/// The host supplies packaged catalogs here; this boundary never reads files.
pub fn compile(
    tree: &File,
    query: Option<&str>,
    libraries: &BTreeMap<String, File>,
    backend: BackendPreference,
) -> Result<CompiledQuery> {
    crate::validation::compiled_tree(tree)?;
    for library in libraries.values() {
        crate::validation::compiled_tree(library)?;
    }
    let tree = crate::resolve_libraries(tree, libraries).map_err(wrapped)?;
    let tree = crate::specialize_models(&tree).map_err(wrapped)?;
    if backend == BackendPreference::Relational || has_graph(&tree, query) {
        compile_relational(&tree, query)
    } else {
        Ok(CompiledQuery {
            program: crate::compile_indexed_branches(&tree, query)?,
            relational: None,
        })
    }
}
