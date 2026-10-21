//! Authenticate one explicitly supplied native API and retain its process lifetime.
use crate::{ModelError, verified_file};
use libloading::Library;
use ort::environment::Environment;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    ffi::CStr,
    io::Write,
    path::{Path, PathBuf},
    sync::{Arc, Mutex, OnceLock},
};

fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Runtime(message.to_string())
}

/// Actual core identity; populated only after byte and native API verification.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RuntimeIdentity {
    pub os: String,
    pub arch: String,
    pub version: String,
    pub api: u32,
    pub bytes: u64,
    pub sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registration {
    format: String,
    libraries: Vec<RuntimeIdentity>,
}

struct ProcessRuntime {
    identity: RuntimeIdentity,
    // This process-global owner survives environment failure and caller drops.
    // ort::set_api stores function pointers into this mapped native library.
    _library: Library,
    environment: OnceLock<Result<Environment, String>>,
}

impl ProcessRuntime {
    fn environment(&self) -> Result<Environment, ModelError> {
        self.environment
            .get_or_init(|| {
                ort::init()
                    .with_name("ken-native-onnx")
                    .build()
                    .map_err(|error| error.to_string())
            })
            .as_ref()
            .cloned()
            .map_err(invalid)
    }
}

static PROCESS: Mutex<Option<Arc<ProcessRuntime>>> = Mutex::new(None);

struct Declaration {
    identity: RuntimeIdentity,
    path: PathBuf,
    verified: Mutex<Option<Arc<ProcessRuntime>>>,
}

/// A cheap explicit declaration. Clones share lazy verification and ownership.
#[derive(Clone)]
pub struct NativeOnnxRuntime(Arc<Declaration>);

impl NativeOnnxRuntime {
    pub(crate) fn private_copy_bytes(&self) -> u64 {
        self.0.identity.bytes
    }
    pub fn from_json(registration: &str, library: &Path) -> Result<Self, ModelError> {
        let registration: Registration = serde_json::from_str(registration)?;
        if registration.format != "ken-native-onnx/1" || !library.is_absolute() {
            return Err(invalid(
                "versioned registration and explicit absolute library path required",
            ));
        }
        // A broader upstream feature could enlarge OrtApi. Never clone an
        // API25 table into a struct compiled for a newer API layout.
        if ort::sys::ORT_API_VERSION != 25 {
            return Err(invalid("this profile requires bindings compiled for API25"));
        }
        let mut names = BTreeSet::new();
        for record in &registration.libraries {
            if !names.insert((&record.os, &record.arch))
                || !matches!(record.os.as_str(), "macos" | "linux")
                || !matches!(record.arch.as_str(), "aarch64" | "x86_64")
                || record.version != "1.25.1"
                || record.api != 25
                || record.bytes == 0
                || record.bytes.checked_add(1).is_none()
                || record.sha256.len() != 64
                || !record
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(invalid("invalid or duplicate native library declaration"));
            }
        }
        let identity = registration
            .libraries
            .into_iter()
            .find(|record| {
                record.os == std::env::consts::OS && record.arch == std::env::consts::ARCH
            })
            .ok_or_else(|| invalid("no registered native runtime for this platform"))?;
        Ok(Self(Arc::new(Declaration {
            identity,
            path: library.to_owned(),
            verified: Mutex::new(None),
        })))
    }

    pub fn load(&self) -> Result<RuntimeIdentity, ModelError> {
        self.environment()?;
        // environment() authenticates this declaration against the process
        // owner, including the actual core's exact native version.
        Ok(self.0.identity.clone())
    }

    /// Observe authenticated code already used by this declaration, without loading it.
    pub fn loaded_identity(&self) -> Result<Option<RuntimeIdentity>, ModelError> {
        let owner = self
            .0
            .verified
            .lock()
            .map_err(|_| invalid("declaration lock poisoned"))?;
        Ok(owner.as_ref().map(|owner| owner.identity.clone()))
    }

    pub(crate) fn environment(&self) -> Result<Environment, ModelError> {
        self.owner()?.environment()
    }

    fn owner(&self) -> Result<Arc<ProcessRuntime>, ModelError> {
        let mut verified = self
            .0
            .verified
            .lock()
            .map_err(|_| invalid("declaration lock poisoned"))?;
        if let Some(owner) = verified.as_ref() {
            return Ok(Arc::clone(owner));
        }
        // Even a warm process must authenticate a new declaration's requested
        // file. A matching descriptor is not evidence that its alias is valid.
        let bytes =
            verified_file::read(&self.0.path, self.0.identity.bytes, &self.0.identity.sha256)
                .map_err(invalid)?;
        let mut global = PROCESS
            .lock()
            .map_err(|_| invalid("process runtime lock poisoned"))?;
        let owner = if let Some(owner) = global.as_ref() {
            if owner.identity != self.0.identity {
                return Err(invalid("conflicting native runtime identity"));
            }
            Arc::clone(owner)
        } else {
            let (library, api) = load_api(&bytes, &self.0.identity)?;
            if !ort::set_api(api) {
                return Err(invalid("native API already registered outside its owner"));
            }
            let owner = Arc::new(ProcessRuntime {
                identity: self.0.identity.clone(),
                _library: library,
                environment: OnceLock::new(),
            });
            // Publish the lifetime owner BEFORE creating an environment. An
            // error or panic there must not unload globally installed pointers.
            *global = Some(Arc::clone(&owner));
            owner
        };
        *verified = Some(Arc::clone(&owner));
        Ok(owner)
    }
}

fn load_api(
    bytes: &[u8],
    identity: &RuntimeIdentity,
) -> Result<(Library, ort::sys::OrtApi), ModelError> {
    let mut private = tempfile::NamedTempFile::new().map_err(invalid)?;
    private.write_all(bytes).map_err(invalid)?;
    private.as_file().sync_all().map_err(invalid)?;
    // SAFETY: the caller explicitly supplies trusted native code through a
    // registration; its entire bytes were authenticated before this private
    // copy. No unchecked reopen of the original library path occurs.
    let library = unsafe { Library::new(private.path()) }.map_err(invalid)?;
    // Linux/macOS keep mapped inodes alive; remove this private copy now, so a
    // process-global handle leaves no persistent temporary library files.
    private.close().map_err(invalid)?;
    // SAFETY: OrtGetApiBase is the pinned core's documented C ABI. Validate
    // nullable pointers/version before reading the API25 layout. The returned
    // Library is retained for every copied function pointer's full lifetime.
    let api = unsafe {
        let get: libloading::Symbol<unsafe extern "C" fn() -> *const ort::sys::OrtApiBase> =
            library
                .get(b"OrtGetApiBase")
                .map_err(|error| invalid(format!("missing OrtGetApiBase: {error}")))?;
        let base = get();
        if base.is_null() {
            return Err(invalid("null native API base"));
        }
        let version = ((*base).GetVersionString)();
        if version.is_null() {
            return Err(invalid("null native version"));
        }
        let version = CStr::from_ptr(version).to_str().map_err(invalid)?;
        if version != identity.version {
            return Err(invalid(format!("native version mismatch: {version}")));
        }
        let api = ((*base).GetApi)(identity.api);
        if api.is_null() {
            return Err(invalid("native API25 unavailable"));
        }
        (*api).clone()
    };
    Ok((library, api))
}
