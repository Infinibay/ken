//! Preserve provider preference and ID diagnostics without claiming GPU execution.
use serde::{Deserialize, Serialize};

const CPU: &str = "CPUExecutionProvider";
const GPU: [&str; 2] = ["CUDAExecutionProvider", "ROCMExecutionProvider"];

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum FastEmbedDevice {
    Unknown,
    Cpu,
    Gpu,
}

#[derive(Clone, Debug)]
pub struct FastEmbedDeviceRequest {
    preference: &'static str,
    // Lexical integer spellings are retained: the original explicit-provider path
    // ignores these IDs, including arbitrarily large Python integers.
    ids: Option<Vec<String>>,
    invalid_ids: bool,
}
impl FastEmbedDeviceRequest {
    pub fn from_inputs(preference: Option<&str>, raw_ids: Option<&str>) -> Self {
        let preference = match preference.unwrap_or("auto").trim().to_lowercase().as_str() {
            "cpu" => "cpu",
            "gpu" | "cuda" => "gpu",
            _ => "auto",
        };
        let mut result = Self {
            preference,
            ids: None,
            invalid_ids: false,
        };
        let raw = raw_ids.unwrap_or("").trim();
        if raw.is_empty() {
            return result;
        }
        let integer =
            onig::Regex::new(r"\A[+-]?\p{Nd}(?:_?\p{Nd})*\z").expect("constant integer pattern");
        let compact = raw.replace(' ', "");
        let mut ids = Vec::new();
        for token in compact.split(',').filter(|token| !token.is_empty()) {
            let token = token.trim();
            if !integer.is_match(token) {
                result.invalid_ids = true;
                return result;
            }
            ids.push(token.into());
        }
        result.ids = Some(ids);
        result
    }
    pub fn preference(&self) -> &str {
        self.preference
    }
    pub fn requested_ids(&self) -> Option<&[String]> {
        self.ids.as_deref()
    }
    pub fn invalid_ids(&self) -> bool {
        self.invalid_ids
    }
    pub fn device_ids_applied(&self) -> bool {
        false
    }
    pub fn providers_for(&self, available: &[&str]) -> Vec<String> {
        let mut providers = Vec::new();
        if self.preference != "cpu" {
            providers.extend(
                GPU.into_iter()
                    .filter(|name| available.contains(name))
                    .map(str::to_owned),
            );
        }
        providers.push(CPU.into());
        providers
    }
}
