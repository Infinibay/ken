//! Existing resource files remain the single bundled-data owner.
use crate::{Bundles, Result, invalid};
pub(crate) mod embedded {
    include!(concat!(env!("OUT_DIR"), "/resources.rs"));
}
pub fn bundled_skills() -> Result<Bundles> {
    let mut out = Bundles::new();
    for &(skill, path, bytes) in embedded::RESOURCES {
        let resources = out.entry(skill.into()).or_default();
        if resources.insert(path.into(), bytes.to_vec()).is_some() {
            return Err(invalid("duplicate bundled skill resource"));
        }
    }
    if out.is_empty() {
        return Err(invalid("The Ken package contains no bundled skills"));
    }
    Ok(out)
}
