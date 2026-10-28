//! Authenticate optional native modules without linking tensor cores into the host.
use crate::{ModelError, verified_file};
use ken_native_model_api::{BACKEND_MLX, BACKEND_TORCH, GetApiV1, KenModelApiV1, api_table};
use libloading::Library;
use serde::{Deserialize, Deserializer, Serialize, de};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex, Weak},
};

fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Runtime(message.to_string())
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct TransformerNativeArtifact {
    pub bytes: u64,
    pub sha256: String,
}

impl TransformerNativeArtifact {
    pub(crate) fn validate(&self) -> bool {
        self.bytes > 0
            && self.bytes.checked_add(1).is_some()
            && self.sha256.len() == 64
            && self
                .sha256
                .bytes()
                .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Platform {
    os: String,
    arch: String,
    core_version: String,
    module: TransformerNativeArtifact,
    #[serde(deserialize_with = "distinct_libraries")]
    libraries: BTreeMap<String, TransformerNativeArtifact>,
}

pub(crate) fn distinct_libraries<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<BTreeMap<String, TransformerNativeArtifact>, D::Error> {
    struct Libraries;
    impl<'de> de::Visitor<'de> for Libraries {
        type Value = BTreeMap<String, TransformerNativeArtifact>;
        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("distinct native library declarations")
        }
        fn visit_map<M: de::MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
            let mut values = BTreeMap::new();
            while let Some((name, artifact)) =
                map.next_entry::<String, TransformerNativeArtifact>()?
            {
                if values.insert(name, artifact).is_some() {
                    return Err(de::Error::custom("duplicate native library declaration"));
                }
            }
            Ok(values)
        }
    }
    deserializer.deserialize_map(Libraries)
}

/// Authenticated module bytes and a declared software version. Actual core
/// software/device/dtype is reported separately by native model preparation.
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct TransformerRuntimeIdentity {
    pub backend: String,
    pub os: String,
    pub arch: String,
    pub declared_core_version: String,
    pub module: TransformerNativeArtifact,
    pub libraries: BTreeMap<String, TransformerNativeArtifact>,
}

impl TransformerRuntimeIdentity {
    fn backend_id(&self) -> u32 {
        match self.backend.as_str() {
            "torch" => BACKEND_TORCH,
            "mlx" => BACKEND_MLX,
            "contract-fixture" => 0xffff_fffe,
            _ => unreachable!("validated declaration"),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registration {
    format: String,
    backend: String,
    runtimes: Vec<Platform>,
}

pub(crate) struct TransformerModule {
    pub(crate) identity: TransformerRuntimeIdentity,
    pub(crate) api: KenModelApiV1,
    // Fields drop in declaration order: no function/library may outlive files.
    _library: Library,
    _files: tempfile::TempDir,
}

static LIVE: Mutex<BTreeMap<u32, Weak<TransformerModule>>> = Mutex::new(BTreeMap::new());

struct Declaration {
    identity: TransformerRuntimeIdentity,
    module_path: PathBuf,
    core_root: PathBuf,
    verified: Mutex<Option<Arc<TransformerModule>>>,
}

/// Parsing is cold; clones share lazy verification and the mapped module owner.
#[derive(Clone)]
pub struct NativeTransformerRuntime(Arc<Declaration>);

impl NativeTransformerRuntime {
    pub(crate) fn private_copy_bytes(&self) -> Result<u64, ModelError> {
        self.0
            .identity
            .libraries
            .values()
            .try_fold(self.0.identity.module.bytes, |total, artifact| {
                total.checked_add(artifact.bytes)
            })
            .ok_or_else(|| invalid("native core private-copy size overflow"))
    }
    pub fn from_json(
        registration: &str,
        module_path: &Path,
        core_root: &Path,
    ) -> Result<Self, ModelError> {
        let registration: Registration = serde_json::from_str(registration)?;
        let version = match registration.backend.as_str() {
            "torch" => "2.9.0",
            "mlx" => "0.32.3",
            "contract-fixture" => "1",
            _ => return Err(invalid("unknown transformer backend")),
        };
        if registration.format != "ken-native-transformer/1"
            || !module_path.is_absolute()
            || !core_root.is_absolute()
        {
            return Err(invalid(
                "versioned declaration and absolute module/core paths required",
            ));
        }
        let mut platforms = BTreeSet::new();
        for record in &registration.runtimes {
            if !platforms.insert((&record.os, &record.arch))
                || !matches!(record.os.as_str(), "macos" | "linux")
                || !matches!(record.arch.as_str(), "aarch64" | "x86_64")
                || (registration.backend == "mlx" && record.os != "macos")
                || record.core_version != version
                || !record.module.validate()
                || record.libraries.is_empty()
                || record
                    .libraries
                    .iter()
                    .any(|(name, artifact)| !safe_relative(name) || !artifact.validate())
            {
                return Err(invalid(
                    "invalid or duplicate transformer runtime declaration",
                ));
            }
        }
        let record = registration
            .runtimes
            .into_iter()
            .find(|v| v.os == std::env::consts::OS && v.arch == std::env::consts::ARCH)
            .ok_or_else(|| invalid("no transformer runtime registered for current platform"))?;
        Ok(Self(Arc::new(Declaration {
            identity: TransformerRuntimeIdentity {
                backend: registration.backend,
                os: record.os,
                arch: record.arch,
                declared_core_version: record.core_version,
                module: record.module,
                libraries: record.libraries,
            },
            module_path: module_path.into(),
            core_root: core_root.into(),
            verified: Mutex::new(None),
        })))
    }

    pub fn backend(&self) -> &str {
        &self.0.identity.backend
    }

    pub fn loaded_identity(&self) -> Result<Option<TransformerRuntimeIdentity>, ModelError> {
        Ok(self
            .0
            .verified
            .lock()
            .map_err(|_| invalid("transformer declaration lock poisoned"))?
            .as_ref()
            .map(|v| v.identity.clone()))
    }

    pub fn load(&self) -> Result<TransformerRuntimeIdentity, ModelError> {
        Ok(self.owner()?.identity.clone())
    }

    pub(crate) fn owner(&self) -> Result<Arc<TransformerModule>, ModelError> {
        let mut verified = self
            .0
            .verified
            .lock()
            .map_err(|_| invalid("transformer declaration lock poisoned"))?;
        if let Some(owner) = verified.as_ref() {
            return Ok(Arc::clone(owner));
        }
        // Authenticate each new declaration even when an identical owner exists.
        // Streaming into private files bounds memory independently of core size.
        let files = tempfile::Builder::new()
            .prefix("ken-transformer-")
            .tempdir()
            .map_err(invalid)?;
        let module = files.path().join(module_name());
        copy(&self.0.module_path, &module, &self.0.identity.module)?;
        for (name, artifact) in &self.0.identity.libraries {
            copy(
                &self.0.core_root.join(name),
                &files.path().join(name),
                artifact,
            )?;
        }
        let mut live = LIVE
            .lock()
            .map_err(|_| invalid("transformer module lock poisoned"))?;
        let id = self.0.identity.backend_id();
        let owner = if let Some(owner) = live.get(&id).and_then(Weak::upgrade) {
            if owner.identity != self.0.identity {
                return Err(invalid(
                    "conflicting live transformer module/core registration",
                ));
            }
            owner
        } else {
            // SAFETY: explicit trusted native-code registration authenticated the
            // private module and its registered dependency closure. The library
            // and files remain owned for the entire copied API table lifetime.
            let library = unsafe { Library::new(&module) }.map_err(invalid)?;
            let api = unsafe {
                let getter: libloading::Symbol<GetApiV1> =
                    library.get(b"ken_model_api_v1\0").map_err(invalid)?;
                api_table(getter(), id).map_err(invalid)?
            };
            let owner = Arc::new(TransformerModule {
                identity: self.0.identity.clone(),
                api,
                _library: library,
                _files: files,
            });
            live.insert(id, Arc::downgrade(&owner));
            owner
        };
        *verified = Some(Arc::clone(&owner));
        Ok(owner)
    }
}

fn module_name() -> String {
    format!("ken_model_backend{}", std::env::consts::DLL_SUFFIX)
}

fn safe_relative(name: &str) -> bool {
    !name.is_empty()
        && !name.contains('\\')
        && !name.contains('\0')
        && name != module_name()
        && name
            .split('/')
            .all(|v| !v.is_empty() && v != "." && v != "..")
        && Path::new(name)
            .components()
            .all(|v| matches!(v, Component::Normal(_)))
}

fn copy(
    source: &Path,
    destination: &Path,
    artifact: &TransformerNativeArtifact,
) -> Result<(), ModelError> {
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(invalid)?;
    }
    let mut output = File::create_new(destination).map_err(invalid)?;
    verified_file::copy(source, artifact.bytes, &artifact.sha256, &mut output).map_err(invalid)?;
    output.sync_all().map_err(invalid)
}
