//! Document-side encoding is explicit; segmentation can use its actual tokenizer.
use crate::{Result, TokenCounter};
pub trait DocumentEncoder {
    fn dim(&self) -> Result<usize>;
    fn token_count(&self, text: &str) -> Result<usize>;
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>>;
}
pub struct EncoderCounter<'a>(pub &'a dyn DocumentEncoder);
impl TokenCounter for EncoderCounter<'_> {
    fn count(&self, text: &str) -> Result<usize> {
        self.0.token_count(text)
    }
}
