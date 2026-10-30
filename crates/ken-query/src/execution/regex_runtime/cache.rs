//! Invocation-local compiled patterns, bounded by entries and source bytes.
use super::*;
#[derive(Default)]
pub struct Cache {
    entries: Vec<(Vec<u32>, String, Dialect, Arc<Pattern>)>,
    bytes: usize,
}
impl Cache {
    pub fn compile(
        &mut self,
        source: &PythonText,
        flags: &str,
        dialect: Dialect,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Arc<Pattern>> {
        check()?;
        if let Some((_, _, _, pattern)) = self
            .entries
            .iter()
            .find(|(text, f, d, _)| text == source.codepoints() && f == flags && *d == dialect)
        {
            return Ok(pattern.clone());
        }
        let pattern = Arc::new(Pattern::compile_text(source, flags, dialect, check)?);
        let bytes = source
            .codepoints()
            .len()
            .saturating_mul(4)
            .saturating_add(flags.len());
        if bytes <= 2 * 1024 * 1024 {
            if self.entries.len() >= 16 || self.bytes.saturating_add(bytes) > 2 * 1024 * 1024 {
                self.entries.clear();
                self.bytes = 0;
            }
            self.entries.push((
                source.codepoints().to_vec(),
                flags.into(),
                dialect,
                pattern.clone(),
            ));
            self.bytes += bytes;
        }
        Ok(pattern)
    }
}
