//! External acquisition and public factory consumer.
#[path = "support/factory.rs"]
mod factory;
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ArtifactRequest, ArtifactTransport, ModelAssets, ModelError,
    PublicModelTransport,
};
use serde_json::json;
use std::{
    io::Read,
    path::Path,
    sync::atomic::{AtomicUsize, Ordering},
};

struct Counted<T> {
    inner: T,
    calls: AtomicUsize,
}
impl<T: ArtifactTransport> ArtifactTransport for Counted<T> {
    fn open(&self, request: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.inner.open(request)
    }
}
struct NoNetwork;
impl ArtifactTransport for NoNetwork {
    fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        Err(ModelError::Runtime(
            "offline transport invocation is forbidden".into(),
        ))
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() == 2 && args[0] == "--factory" {
        return factory::run(&factory::read(Path::new(&args[1]))?);
    }
    if args.len() != 3
        || !matches!(args[2].as_str(), "public" | "offline")
        || args[..2].iter().any(|s| !Path::new(s).is_absolute())
    {
        return Err(
            "explicit absolute registration/cache paths and public|offline policy required".into(),
        );
    }
    let mut raw = String::new();
    std::fs::File::open(&args[0])?
        .take(1024 * 1024 + 1)
        .read_to_string(&mut raw)?;
    if raw.len() > 1024 * 1024 {
        return Err("oversized asset declaration".into());
    }
    let assets = ModelAssets::from_json(&raw)?;
    let cache = ArtifactCache::new(Path::new(&args[1]))?;
    let (resolved, calls) = if args[2] == "offline" {
        let transport = Counted {
            inner: NoNetwork,
            calls: AtomicUsize::new(0),
        };
        let path = cache.resolve(&assets, AcquisitionPolicy::Offline, &transport)?;
        (path, transport.calls.load(Ordering::SeqCst))
    } else {
        let transport = Counted {
            inner: PublicModelTransport::new()?,
            calls: AtomicUsize::new(0),
        };
        let path = cache.resolve(&assets, AcquisitionPolicy::Public, &transport)?;
        (path, transport.calls.load(Ordering::SeqCst))
    };
    println!(
        "{}",
        json!({"format":"ken-model-integration-probe/1","operation":"acquire",
        "asset_fingerprint":assets.fingerprint(),"resolved":resolved,"policy":args[2],"transport_open_calls":calls})
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::factory;
    use serde_json::json;
    #[test]
    fn factory_protocol_is_bounded_explicit_and_rejects_expected_outputs() {
        let request = json!({"format":"ken-model-factory-request/1","policy":"offline",
            "cache_root":"/tmp/cache","private_parent":"/tmp/private","bundled_npz":"/tmp/model.npz",
            "source_overrides":{},"device":{"kind":"cpu"},"fastembed_device":"cpu",
            "selection":{"kind":"legacy_encoder","name":"ken/static-qwen3-r512-v2"},
            "cases":[{"id":"empty","call":{"operation":"passages","texts":[]}}]});
        assert!(factory::parse(&serde_json::to_vec(&request).unwrap()).is_ok());
        let mut bad = request.clone();
        bad["expected"] = json!([1., 0.]);
        assert!(factory::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = request.clone();
        bad["cases"][0]["call"]["expected"] = json!([]);
        assert!(factory::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = request.clone();
        bad["cache_root"] = json!("relative");
        assert!(factory::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = request.clone();
        bad["cases"][0]["call"] = json!({"operation":"concurrent_query","text":"x","workers":9});
        assert!(factory::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = request.clone();
        bad["cases"]
            .as_array_mut()
            .unwrap()
            .push(request["cases"][0].clone());
        assert!(factory::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    }
}
