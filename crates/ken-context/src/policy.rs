use crate::{Error, Result};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FusionMode {
    Legacy,
    LogOdds,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PprMode {
    Off,
    Add,
    Replace,
}
#[derive(Clone, Debug)]
pub struct Policy {
    pub fusion: FusionMode,
    pub ppr: PprMode,
    pub adaptive: bool,
    pub lift: bool,
    pub fuzzy_resolve_cap: usize,
    pub family_weights: BTreeMap<String, f64>,
    pub fusion_scale: f64,
    pub fusion_gate: f64,
    pub ppr_alpha: f64,
    pub ppr_max: f64,
    pub ppr_min_fraction: f64,
    pub ppr_max_neighbors: i64,
}
impl Default for Policy {
    fn default() -> Self {
        Self {
            fusion: FusionMode::Legacy,
            ppr: PprMode::Off,
            adaptive: false,
            lift: false,
            fuzzy_resolve_cap: 2000,
            family_weights: BTreeMap::from([
                ("explicit".into(), 1.30),
                ("behavioral".into(), 1.15),
                ("nametext".into(), 1.),
            ]),
            fusion_scale: 1.6,
            fusion_gate: 1.5,
            ppr_alpha: 0.8,
            ppr_max: 0.6,
            ppr_min_fraction: 0.4,
            ppr_max_neighbors: 3,
        }
    }
}
impl Policy {
    /// Capture once at the host boundary. Rank operations never read environment.
    pub fn capture(env: &BTreeMap<String, String>) -> Result<Self> {
        let mut p = Self::default();
        let read = |key: &str| {
            env.get(key)
                .map(|s| s.trim().to_lowercase())
                .unwrap_or_default()
        };
        let flag = |key: &str| matches!(read(key).as_str(), "1" | "true" | "on" | "yes");
        let number = |key: &str, default: f64| {
            env.get(key)
                .and_then(|s| s.trim().parse::<f64>().ok())
                .unwrap_or(default)
        };
        p.fusion = if read("KEN_RANKER_FUSION") == "logodds" {
            FusionMode::LogOdds
        } else {
            FusionMode::Legacy
        };
        p.ppr = match read("KEN_RANKER_PPR").as_str() {
            "add" | "additive" => PprMode::Add,
            "1" | "true" | "on" | "yes" | "replace" => PprMode::Replace,
            _ => PprMode::Off,
        };
        p.adaptive = flag("KEN_RANKER_ADAPTIVE");
        p.lift = flag("KEN_RANKER_LIFT");
        if let Some(raw) = env.get("KEN_FUZZY_RESOLVE_CAP") {
            p.fuzzy_resolve_cap = raw
                .trim()
                .parse()
                .map_err(|_| Error::Invalid("invalid KEN_FUZZY_RESOLVE_CAP".into()))?;
        }
        for (family, key) in [
            ("explicit", "KEN_FUSE_W_EXPLICIT"),
            ("behavioral", "KEN_FUSE_W_BEHAVIORAL"),
            ("nametext", "KEN_FUSE_W_NAMETEXT"),
        ] {
            p.family_weights
                .insert(family.into(), number(key, p.family_weights[family]));
        }
        p.fusion_scale = number("KEN_FUSE_SCALE", p.fusion_scale);
        p.fusion_gate = number("KEN_FUSE_GATE", p.fusion_gate);
        p.ppr_alpha = number("KEN_PPR_ALPHA", p.ppr_alpha);
        p.ppr_max = number("KEN_PPR_MAX", p.ppr_max);
        p.ppr_min_fraction = number("KEN_PPR_MINFRAC", p.ppr_min_fraction);
        let neighbors = number("KEN_PPR_MAXN", p.ppr_max_neighbors as f64);
        if !neighbors.is_finite() || neighbors < i64::MIN as f64 || neighbors > i64::MAX as f64 {
            return Err(Error::Invalid("invalid KEN_PPR_MAXN".into()));
        }
        p.ppr_max_neighbors = neighbors as i64;
        Ok(p)
    }
}
