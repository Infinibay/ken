//! Explicit cold declarations own authenticated private CT2 module mappings.
use crate::translation_abi::{self as abi, Api, Buffer, Info, POLICY, Span, invalid};
use crate::{ModelError, TransformerNativeArtifact as Artifact, verified_file};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    ffi::c_void,
    fs::File,
    path::{Path, PathBuf},
    sync::{Arc, Mutex, Weak},
};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Platform {
    os: String,
    arch: String,
    core_version: String,
    abi: u32,
    module: Artifact,
    #[serde(deserialize_with = "crate::transformer_runtime::distinct_libraries")]
    libraries: BTreeMap<String, Artifact>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registration {
    format: String,
    runtimes: Vec<Platform>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Core {
    format: String,
    runtimes: Vec<CorePlatform>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CorePlatform {
    os: String,
    arch: String,
    version: String,
    libraries: BTreeMap<String, Artifact>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct NativeTranslationRuntimeIdentity {
    pub core_version: String,
    pub float_backend: String,
    pub int8_backend: String,
    pub module: Artifact,
    pub libraries: BTreeMap<String, Artifact>,
}
struct Module {
    declaration: Platform,
    identity: NativeTranslationRuntimeIdentity,
    api: Api,
    // Library is unloaded before its authenticated files are removed.
    _library: libloading::Library,
    _files: tempfile::TempDir,
}
static LIVE: Mutex<Weak<Module>> = Mutex::new(Weak::new());
struct Declaration {
    platform: Platform,
    module_path: PathBuf,
    core_root: PathBuf,
    loaded: Mutex<Option<Arc<Module>>>,
}
/// Parsing performs no IO. Clones share retryable lazy verification and ownership.
#[derive(Clone)]
pub struct NativeTranslationRuntime(Arc<Declaration>);

impl NativeTranslationRuntime {
    pub(crate) fn private_copy_bytes(&self) -> Result<u64, ModelError> {
        self.0
            .platform
            .libraries
            .values()
            .try_fold(self.0.platform.module.bytes, |total, artifact| {
                total.checked_add(artifact.bytes)
            })
            .ok_or_else(|| invalid("translation runtime footprint overflow"))
    }
    pub fn from_json(
        registration: &str,
        module_path: &Path,
        core_root: &Path,
    ) -> Result<Self, ModelError> {
        let value: Registration = serde_json::from_str(registration)?;
        let core: Core =
            serde_json::from_str(include_str!("../resources/ct2-runtime-libraries.json"))?;
        if core.format != "ken-native-translation-core/1"
            || value.format != "ken-native-translation/1"
            || !module_path.is_absolute()
            || !core_root.is_absolute()
            || value.runtimes.len() != 1
        {
            return Err(invalid(
                "versioned translation declaration and absolute paths required",
            ));
        }
        let platform = value.runtimes.into_iter().next().expect("one runtime");
        let registered = core
            .runtimes
            .iter()
            .find(|v| v.os == platform.os && v.arch == platform.arch);
        if platform.os != "linux"
            || platform.arch != "x86_64"
            || platform.os != std::env::consts::OS
            || platform.arch != std::env::consts::ARCH
            || platform.core_version != "4.8.2"
            || platform.abi != 1
            || !platform.module.validate()
            || !registered.is_some_and(|v| {
                v.version == platform.core_version && v.libraries == platform.libraries
            })
        {
            return Err(invalid(
                "unregistered translation platform, ABI or CPU core",
            ));
        }
        Ok(Self(Arc::new(Declaration {
            platform,
            module_path: module_path.into(),
            core_root: core_root.into(),
            loaded: Mutex::new(None),
        })))
    }
    pub fn loaded_identity(&self) -> Result<Option<NativeTranslationRuntimeIdentity>, ModelError> {
        Ok(self
            .0
            .loaded
            .lock()
            .map_err(|_| invalid("translation declaration lock poisoned"))?
            .as_ref()
            .map(|v| v.identity.clone()))
    }
    pub fn load(&self) -> Result<NativeTranslationRuntimeIdentity, ModelError> {
        Ok(self.owner()?.identity.clone())
    }
    fn owner(&self) -> Result<Arc<Module>, ModelError> {
        let mut loaded = self
            .0
            .loaded
            .lock()
            .map_err(|_| invalid("translation declaration lock poisoned"))?;
        if let Some(owner) = loaded.as_ref() {
            return Ok(Arc::clone(owner));
        }
        let files = tempfile::Builder::new()
            .prefix("ken-ct2-core-")
            .tempdir()
            .map_err(invalid)?;
        let module_path = files.path().join("libken_ct2_backend.so");
        copy(&self.0.module_path, &module_path, &self.0.platform.module)?;
        for (name, artifact) in &self.0.platform.libraries {
            copy(
                &self.0.core_root.join(name),
                &files.path().join(name),
                artifact,
            )?;
        }
        let mut live = LIVE
            .lock()
            .map_err(|_| invalid("translation module lock poisoned"))?;
        let owner = if let Some(owner) = live.upgrade() {
            if owner.declaration != self.0.platform {
                return Err(invalid("conflicting live translation module registration"));
            }
            owner
        } else {
            // SAFETY: all mapped code and dependencies were copied from the
            // explicit authenticated declaration. Deep binding keeps this core
            // independent of any legacy CT2 symbols linked into the host.
            #[cfg(all(target_os = "linux", target_env = "gnu"))]
            let library: libloading::Library = unsafe {
                libloading::os::unix::Library::open(
                    Some(&module_path),
                    libc::RTLD_NOW | libc::RTLD_LOCAL | libc::RTLD_DEEPBIND,
                )
            }
            .map_err(invalid)?
            .into();
            #[cfg(not(all(target_os = "linux", target_env = "gnu")))]
            let library = unsafe { libloading::Library::new(&module_path) }.map_err(invalid)?;
            let api = unsafe {
                let getter: libloading::Symbol<abi::Getter> =
                    library.get(b"ken_translation_api_v1\0").map_err(invalid)?;
                abi::table(getter())?
            };
            let mut info = Info::default();
            let mut error = Buffer::default();
            unsafe {
                let status = api.info.expect("validated API")(&mut info, &mut error);
                api.status(status, error)?;
            }
            if (info.major, info.minor, info.patch) != (4, 8, 2) {
                return Err(invalid("actual translation core version differs"));
            }
            let identity = NativeTranslationRuntimeIdentity {
                core_version: "4.8.2".into(),
                float_backend: backend(info.float_backend)?.into(),
                int8_backend: backend(info.int8_backend)?.into(),
                module: self.0.platform.module.clone(),
                libraries: self.0.platform.libraries.clone(),
            };
            let owner = Arc::new(Module {
                declaration: self.0.platform.clone(),
                identity,
                api,
                _library: library,
                _files: files,
            });
            *live = Arc::downgrade(&owner);
            owner
        };
        *loaded = Some(Arc::clone(&owner));
        Ok(owner)
    }
    pub(crate) fn session(&self, path: &Path) -> Result<NativeTranslator, ModelError> {
        let owner = self.owner()?;
        let path = path
            .to_str()
            .ok_or_else(|| invalid("UTF-8 native model path required"))?;
        let mut handle = std::ptr::null_mut();
        let mut error = Buffer::default();
        let status = unsafe {
            owner.api.create.expect("validated API")(
                Span::new(path.as_bytes()),
                &POLICY,
                &mut handle,
                &mut error,
            )
        };
        let session = NativeTranslator { handle, owner };
        unsafe {
            session.owner.api.status(status, error)?;
        }
        if session.handle.is_null() {
            return Err(invalid("null native translation session"));
        }
        Ok(session)
    }
}
fn backend(value: u32) -> Result<&'static str, ModelError> {
    match value {
        1 => Ok("MKL"),
        2 => Ok("DNNL"),
        _ => Err(invalid("unregistered x86 translation GEMM backend")),
    }
}
fn copy(source: &Path, destination: &Path, artifact: &Artifact) -> Result<(), ModelError> {
    let mut output = File::create_new(destination).map_err(invalid)?;
    verified_file::copy(source, artifact.bytes, &artifact.sha256, &mut output).map_err(invalid)?;
    output.sync_all().map_err(invalid)
}
pub(crate) struct NativeTranslator {
    handle: *mut c_void,
    owner: Arc<Module>,
}
// A session is moved only while its Rust owner holds the expansion mutex;
// CT2 owns and joins its worker threads when the handle is destroyed.
unsafe impl Send for NativeTranslator {}
impl Drop for NativeTranslator {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe { self.owner.api.destroy.expect("validated API")(self.handle) };
        }
    }
}
impl NativeTranslator {
    pub fn replicas(&self) -> usize {
        unsafe { self.owner.api.num_replicas.expect("validated API")(self.handle) }
    }
    pub fn backends(&self) -> Result<(&'static str, &'static str), ModelError> {
        let identity = &self.owner.identity;
        let name = |v: &str| match v {
            "DNNL" => Ok("DNNL"),
            "MKL" => Ok("MKL"),
            _ => Err(invalid("unregistered CPU backend")),
        };
        Ok((
            name(&identity.float_backend)?,
            name(&identity.int8_backend)?,
        ))
    }
    pub fn translate(&self, tokens: &[String]) -> Result<Vec<Vec<String>>, ModelError> {
        let spans: Vec<_> = tokens.iter().map(|v| Span::new(v.as_bytes())).collect();
        let mut output = Buffer::default();
        let mut error = Buffer::default();
        unsafe {
            let status = self.owner.api.translate.expect("validated API")(
                self.handle,
                spans.as_ptr(),
                spans.len(),
                &mut output,
                &mut error,
            );
            // Always release both independently owned buffers, even on errors.
            let bytes = self.owner.api.take(output);
            self.owner.api.status(status, error)?;
            Ok(vec![abi::hypothesis(&bytes?)?])
        }
    }
}
