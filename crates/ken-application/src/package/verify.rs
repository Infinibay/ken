//! Verify declared bytes through held directory handles; never load packaged code.
use super::{
    Result, invalid,
    model::{Manifest, PackageInfo},
};
use serde::{
    Deserialize, Deserializer,
    de::{self, MapAccess, Visitor},
};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    fs::{self, File},
    io::Read,
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::{Path, PathBuf},
};
pub(crate) const MAX_MANIFEST: u64 = 2 * 1024 * 1024;
pub(crate) fn hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
pub(crate) fn relative(value: &str) -> Result<PathBuf> {
    if value.is_empty()
        || value.contains(['\0', '\\'])
        || value.starts_with('/')
        || value
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(invalid("one confined relative package path required"));
    }
    Ok(value.into())
}
pub(crate) struct Directory {
    pub file: File,
    pub path: PathBuf,
}
impl Directory {
    pub fn open(path: &Path) -> Result<Self> {
        let path = path.canonicalize()?;
        let file = ken_core::source_reader::open_directory(&path)?;
        Ok(Self { file, path })
    }
    pub fn proc(&self) -> PathBuf {
        PathBuf::from(format!("/proc/self/fd/{}", self.file.as_raw_fd()))
    }
    pub fn child(&self, path: &Path) -> Result<Self> {
        let file = ken_core::source_reader::open_relative(&self.file, path, true)?;
        Ok(Self {
            file,
            path: self.path.join(path),
        })
    }
    pub fn read(&self, path: &Path, maximum: u64) -> Result<Vec<u8>> {
        let file = ken_core::source_reader::open_relative(&self.file, path, false)?;
        if !file.metadata()?.is_file() || file.metadata()?.len() > maximum {
            return Err(invalid("oversized or nonregular package metadata"));
        }
        let mut bytes = Vec::new();
        file.take(maximum + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > maximum {
            return Err(invalid("package metadata grew beyond bound"));
        }
        Ok(bytes)
    }
    pub fn unchanged(&self) -> Result<()> {
        let named = fs::symlink_metadata(&self.path)?;
        let held = self.file.metadata()?;
        if !named.is_dir()
            || named.file_type().is_symlink()
            || (named.dev(), named.ino()) != (held.dev(), held.ino())
        {
            return Err(invalid("owned package directory name changed"));
        }
        Ok(())
    }
}
struct Distinct(BTreeMap<String, Box<RawValue>>);
impl<'de> Deserialize<'de> for Distinct {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = Distinct;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("distinct object keys")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Distinct, M::Error> {
                let mut values = BTreeMap::new();
                while let Some((key, value)) = map.next_entry::<String, Box<RawValue>>()? {
                    if values.insert(key, value).is_some() {
                        return Err(de::Error::custom("duplicate package metadata key"));
                    }
                }
                Ok(Distinct(values))
            }
        }
        deserializer.deserialize_map(V)
    }
}
pub(crate) fn strict_json(raw: &str) -> Result<()> {
    fn check(raw: &str, depth: usize) -> Result<()> {
        if depth > 64 {
            return Err(invalid("package metadata depth exceeds64"));
        }
        let raw = raw.trim_start();
        if raw.starts_with('{') {
            for value in serde_json::from_str::<Distinct>(raw)?.0.values() {
                check(value.get(), depth + 1)?;
            }
        } else if raw.starts_with('[') {
            for value in serde_json::from_str::<Vec<Box<RawValue>>>(raw)? {
                check(value.get(), depth + 1)?;
            }
        } else {
            let _: Box<RawValue> = serde_json::from_str(raw)?;
        }
        Ok(())
    }
    check(raw, 0)
}
fn descendants(
    directory: &Directory,
    prefix: &str,
    files: &mut BTreeSet<String>,
    directories: &mut BTreeSet<String>,
    count: &mut usize,
) -> Result<()> {
    for entry in fs::read_dir(directory.proc())? {
        let entry = entry?;
        *count += 1;
        if *count > 40_000 {
            return Err(invalid("package tree exceeds40000 entries"));
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| invalid("UTF8 package paths required"))?;
        relative(&name)?;
        let relative_name = if prefix.is_empty() {
            name.clone()
        } else {
            format!("{prefix}/{name}")
        };
        let metadata = fs::symlink_metadata(entry.path())?;
        if metadata.file_type().is_symlink() {
            return Err(invalid("package symlinks are forbidden"));
        }
        if metadata.is_dir() {
            directories.insert(relative_name.clone());
            let child = directory.child(Path::new(&name))?;
            descendants(&child, &relative_name, files, directories, count)?;
        } else if metadata.is_file() {
            files.insert(relative_name);
        } else {
            return Err(invalid("special package files are forbidden"));
        }
    }
    Ok(())
}
fn owned_resource(
    value: &serde_json::Value,
    root: &str,
    files: &BTreeMap<String, super::model::FileRecord>,
    directory: bool,
) -> Result<String> {
    let value = value
        .as_str()
        .ok_or_else(|| invalid("relative installed resource path required"))?;
    if value.starts_with('/') || value.contains(['\0', '\\']) {
        return Err(invalid("portable package resource path required"));
    }
    let mut parts = root
        .split('/')
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    for part in value.split('/') {
        match part {
            ".." => {
                if parts.pop().is_none() {
                    return Err(invalid("resource path escapes release"));
                }
            }
            "." | "" => {}
            part => parts.push(part.into()),
        }
    }
    let path = parts.join("/");
    if !directory && !files.contains_key(&path) {
        return Err(invalid(format!("resource file is not declared: {path}")));
    }
    Ok(path)
}
fn resources(directory: &Directory, manifest: &Manifest) -> Result<()> {
    let bytes = directory.read(&relative(&manifest.resources)?, 1024 * 1024)?;
    let raw =
        std::str::from_utf8(&bytes).map_err(|_| invalid("UTF8 resource metadata required"))?;
    strict_json(raw)?;
    let value: serde_json::Value = serde_json::from_str(raw)?;
    if value["format"] != "ken-search-installation/1" {
        return Err(invalid("registered search installation required"));
    }
    if value["private_parent"] != "../../../var/private"
        || value["cache_parent"] != "../../../var/cache"
    {
        return Err(invalid(
            "runtime private/cache data must reside in prefix/var outside authenticated release",
        ));
    }
    let base = "resources";
    for key in ["grammar_manifest", "bundled_npz"] {
        owned_resource(&value[key], base, &manifest.files, false)?;
    }
    owned_resource(&value["ranking_directory"], base, &manifest.files, true)?;
    if let Some(sources) = value["sources"].as_object() {
        for path in sources.values() {
            owned_resource(path, base, &manifest.files, true)?;
        }
    } else {
        return Err(invalid("source override map required"));
    }
    if !value["onnx_library"].is_null() {
        owned_resource(&value["onnx_library"], base, &manifest.files, false)?;
    }
    for key in ["translation", "torch"] {
        if !value[key].is_null() {
            owned_resource(&value[key]["module_path"], base, &manifest.files, false)?;
            owned_resource(&value[key]["core_root"], base, &manifest.files, true)?;
        }
    }
    if !value["catalogue_extensions"].is_null() {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Catalogue {
            path: String,
            bytes: u64,
            sha256: String,
        }
        let declared: Catalogue = serde_json::from_value(value["catalogue_extensions"].clone())?;
        let path = owned_resource(
            &serde_json::Value::String(declared.path),
            base,
            &manifest.files,
            false,
        )?;
        let record = manifest
            .files
            .get(&path)
            .ok_or_else(|| invalid("catalogue resource is not declared"))?;
        if record.bytes != declared.bytes || record.sha256 != declared.sha256 {
            return Err(invalid(
                "catalogue declaration differs from authenticated inventory identity",
            ));
        }
    }
    Ok(())
}
pub(crate) fn authenticate(root: &Path) -> Result<(PackageInfo, Manifest, Vec<u8>)> {
    if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        return Err(invalid("native packages currently require Linux x86_64"));
    }
    let directory = Directory::open(root)?;
    let manifest_file =
        ken_core::source_reader::open_relative(&directory.file, Path::new("FILES.json"), false)?;
    let metadata = manifest_file.metadata()?;
    if metadata.nlink() != 1 || (metadata.mode() & 0o7777) != 0o444 {
        return Err(invalid("FILES manifest must be independent read-only data"));
    }
    let raw = directory.read(Path::new("FILES.json"), MAX_MANIFEST)?;
    let text = std::str::from_utf8(&raw).map_err(|_| invalid("UTF8 manifest required"))?;
    strict_json(text)?;
    let manifest: Manifest = serde_json::from_slice(&raw)?;
    if manifest.format != "ken-native-package/1"
        || manifest.target.os != "linux"
        || manifest.target.arch != "x86_64"
        || manifest.target.device != "cpu"
        || manifest.resources != "resources/search.json"
        || manifest.files.is_empty()
        || manifest.files.len() > 20_000
    {
        return Err(invalid(
            "bounded Linux x86 CPU package declaration required",
        ));
    }
    let expected = BTreeMap::from([
        ("launcher".to_owned(), "ken".to_owned()),
        ("cli".into(), "ken-rs".into()),
        ("check_worker".into(), "ken-check-worker".into()),
        ("git".into(), "git".into()),
    ]);
    if manifest.entrypoints != expected {
        return Err(invalid(
            "exact native launcher/CLI/checkworker/Git entrypoints required",
        ));
    }
    for key in ["source", "build", "runtime", "qualification"] {
        if !manifest.provenance[key].is_object() {
            return Err(invalid(
                "source/build/runtime/qualification provenance required",
            ));
        }
    }
    let source = &manifest.provenance["source"];
    if source["commit"].as_str().is_none_or(|sha| {
        sha.len() != 40
            || !sha
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    }) || !source["dirty"].is_boolean()
        || !manifest.provenance["qualification"]["accepted"].is_boolean()
    {
        return Err(invalid("explicit source and qualification state required"));
    }
    let mut total = 0u64;
    let mut actual = BTreeSet::new();
    let mut directories = BTreeSet::new();
    descendants(&directory, "", &mut actual, &mut directories, &mut 0)?;
    let declared = manifest
        .files
        .keys()
        .cloned()
        .chain(std::iter::once("FILES.json".into()))
        .collect::<BTreeSet<_>>();
    if actual != declared
        || directories.iter().any(|directory| {
            !declared
                .iter()
                .any(|name| name.starts_with(&(directory.clone() + "/")))
        })
    {
        return Err(invalid(
            "package contains missing or undeclared files/directories",
        ));
    }
    for (name, record) in &manifest.files {
        let path = relative(name)?;
        if name == "FILES.json"
            || !hex(&record.sha256)
            || !matches!(record.mode, 0o444 | 0o555)
            || record.bytes > 16 * 1024 * 1024 * 1024
        {
            return Err(invalid("invalid package artifact identity/mode/bound"));
        }
        total = total
            .checked_add(record.bytes)
            .filter(|total| *total <= 64 * 1024 * 1024 * 1024)
            .ok_or_else(|| invalid("package exceeds64GiB"))?;
        let mut file = ken_core::source_reader::open_relative(&directory.file, &path, false)?;
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || metadata.len() != record.bytes
            || (metadata.mode() & 0o7777) != record.mode
        {
            return Err(invalid(format!(
                "package artifact metadata differs: {name}"
            )));
        }
        let mut hash = Sha256::new();
        let mut bytes = 0u64;
        let mut buffer = [0u8; 65536];
        loop {
            let count = file.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            bytes += count as u64;
            if bytes > record.bytes {
                return Err(invalid("package file grew while hashing"));
            }
            hash.update(&buffer[..count]);
        }
        if bytes != record.bytes || format!("{:x}", hash.finalize()) != record.sha256 {
            return Err(invalid(format!("package artifact hash differs: {name}")));
        }
    }
    for name in manifest.entrypoints.values() {
        let record = manifest
            .files
            .get(name)
            .ok_or_else(|| invalid("native entrypoint is undeclared"))?;
        if record.mode != 0o555 {
            return Err(invalid("native entrypoint must be read-execute only"));
        }
        let mut file =
            ken_core::source_reader::open_relative(&directory.file, Path::new(name), false)?;
        let mut header = [0u8; 20];
        file.read_exact(&mut header)?;
        if !header.starts_with(b"\x7fELF\x02\x01")
            || u16::from_le_bytes([header[18], header[19]]) != 62
        {
            return Err(invalid("Linux x86_64 ELF entrypoint required"));
        }
    }
    resources(&directory, &manifest)?;
    directory.unchanged()?;
    let info = PackageInfo {
        manifest_sha256: format!("{:x}", Sha256::digest(&raw)),
        target: manifest.target.clone(),
        entrypoints: manifest.entrypoints.clone(),
        resources: manifest.resources.clone(),
        provenance: manifest.provenance.clone(),
        file_count: manifest.files.len(),
        total_bytes: total,
    };
    Ok((info, manifest, raw))
}
