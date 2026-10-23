//! Read actual config bytes; alias dependencies remain the alias owner's rule.
use super::{ImportError, aliases::AliasResolver};
use std::{collections::BTreeMap, fs, path::Path};
pub(super) struct ProjectImportInputs {
    pub bytes: BTreeMap<String, Vec<u8>>,
    pub aliases: AliasResolver,
}
impl ProjectImportInputs {
    pub fn read(root: &Path, files: &[String]) -> Result<Self, ImportError> {
        let mut bytes = BTreeMap::new();
        let aliases = {
            let mut load = |name: &str| {
                let value = fs::read(root.join(name)).ok()?;
                bytes.insert(name.to_owned(), value.clone());
                Some(value)
            };
            AliasResolver::from_loader(files, &mut load)?
        };
        for name in files {
            if (name.ends_with("go.mod") || name.ends_with("composer.json"))
                && let Ok(value) = fs::read(root.join(name))
            {
                bytes.insert(name.clone(), value);
            }
        }
        Ok(Self { bytes, aliases })
    }
}
