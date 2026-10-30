//! Prefix ownership, recovery and atomic activation. No packaged program is executed.
use super::{
    Result, invalid,
    model::*,
    verify::{self, Directory},
};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::{
        fd::AsRawFd,
        unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt, symlink},
    },
    path::{Path, PathBuf},
};
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Owner {
    format: String,
    id: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Activation {
    format: String,
    owner: String,
    current: String,
    previous: Option<String>,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Identity {
    device: u64,
    inode: u64,
}
impl Identity {
    fn of(directory: &Directory) -> Result<Self> {
        let m = directory.file.metadata()?;
        Ok(Self {
            device: m.dev(),
            inode: m.ino(),
        })
    }
    fn matches(&self, directory: &Directory) -> Result<bool> {
        let actual = Self::of(directory)?;
        Ok((self.device, self.inode) == (actual.device, actual.inode))
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Transaction {
    format: String,
    owner: String,
    id: String,
    stage: Identity,
    activation: Option<(String, Identity)>,
}
struct Lock(File);
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
struct Prefix {
    root: Directory,
    meta: Directory,
    owner: Owner,
    _lock: Lock,
}
#[derive(Clone)]
pub struct PackageApplication {
    prefix: PathBuf,
}
fn nonce() -> Result<String> {
    let mut raw = [0u8; 16];
    File::open("/dev/urandom")?.read_exact(&mut raw)?;
    Ok(raw.iter().map(|b| format!("{b:02x}")).collect())
}
fn id(value: &str) -> bool {
    value.len() == 32
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn exists(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}
fn directory(parent: &Directory, name: &str) -> Result<Directory> {
    verify::relative(name)?;
    let path = parent.proc().join(name);
    if !exists(&path)? {
        fs::DirBuilder::new().mode(0o700).create(&path)?;
        parent.file.sync_all()?;
    }
    parent.child(Path::new(name))
}
fn write_new(parent: &Directory, name: &str, bytes: &[u8], mode: u32) -> Result<()> {
    verify::relative(name)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .custom_flags(libc::O_NOFOLLOW)
        .open(parent.proc().join(name))?;
    file.write_all(bytes)?;
    file.set_permissions(fs::Permissions::from_mode(mode))?;
    file.sync_all()?;
    parent.file.sync_all()?;
    Ok(())
}
fn replace_json(parent: &Directory, name: &str, value: &impl Serialize) -> Result<()> {
    let temporary = format!(".json-{}", nonce()?);
    write_new(parent, &temporary, &serde_json::to_vec(value)?, 0o600)?;
    fs::rename(parent.proc().join(&temporary), parent.proc().join(name))?;
    parent.file.sync_all()?;
    Ok(())
}
fn read_json<T: serde::de::DeserializeOwned>(parent: &Directory, name: &str) -> Result<T> {
    let bytes = parent.read(Path::new(name), 2 * 1024 * 1024)?;
    let raw = std::str::from_utf8(&bytes).map_err(|_| invalid("UTF8 owned metadata required"))?;
    verify::strict_json(raw)?;
    Ok(serde_json::from_slice(&bytes)?)
}
fn move_new(from: &Directory, name: &str, to: &Directory, destination: &str) -> Result<()> {
    #[cfg(target_os = "linux")]
    {
        let source = std::ffi::CString::new(name).map_err(|_| invalid("invalid rename source"))?;
        let target = std::ffi::CString::new(destination)
            .map_err(|_| invalid("invalid rename destination"))?;
        let result = unsafe {
            libc::syscall(
                libc::SYS_renameat2,
                from.file.as_raw_fd(),
                source.as_ptr(),
                to.file.as_raw_fd(),
                target.as_ptr(),
                libc::RENAME_NOREPLACE,
            )
        };
        if result != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        from.file.sync_all()?;
        to.file.sync_all()?;
        Ok(())
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (from, name, to, destination);
        Err(invalid("native package publication requires Linux"))
    }
}
fn remove_tree(parent: &Directory, name: &str, expected: Identity, links: bool) -> Result<()> {
    let child = parent.child(Path::new(name))?;
    if !expected.matches(&child)? {
        return Err(invalid("staging directory identity changed; preserving it"));
    }
    fn clear(dir: &Directory, links: bool) -> Result<()> {
        for entry in fs::read_dir(dir.proc())? {
            let entry = entry?;
            let name = entry.file_name();
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() {
                if !links {
                    return Err(invalid(
                        "unexpected symlink in owned staging; preserving it",
                    ));
                }
                fs::remove_file(dir.proc().join(&name))?;
                continue;
            }
            if metadata.is_dir() {
                let child = dir.child(Path::new(&name))?;
                clear(&child, links)?;
                fs::remove_dir(dir.proc().join(&name))?;
            } else if metadata.is_file() {
                fs::remove_file(dir.proc().join(&name))?;
            } else {
                return Err(invalid("unexpected special staging file"));
            }
        }
        dir.file.sync_all()?;
        Ok(())
    }
    clear(&child, links)?;
    fs::remove_dir(parent.proc().join(name))?;
    parent.file.sync_all()?;
    Ok(())
}
const LINKS: [(&str, &str); 4] = [
    ("current", ".ken-package/active/current"),
    ("previous", ".ken-package/active/previous"),
    ("bin/ken", "../current/ken"),
    ("bin/ken-rs", "../current/ken"),
];
impl Prefix {
    fn open(path: &Path, create: bool) -> Result<Option<Self>> {
        if !path.exists() {
            if !create {
                return Ok(None);
            }
            fs::create_dir_all(path)?;
        }
        let root = Directory::open(path)?;
        if !exists(&root.proc().join(".ken-package"))? {
            if !create {
                return Ok(None);
            }
            for (name, _) in LINKS {
                if exists(&root.proc().join(name))? {
                    return Err(invalid(format!("refusing unowned prefix path: {name}")));
                }
            }
            let owner = Owner {
                format: "ken-native-prefix/1".into(),
                id: nonce()?,
            };
            let stage_name = format!(".ken-package-init-{}", owner.id);
            let stage = directory(&root, &stage_name)?;
            write_new(&stage, "owner.json", &serde_json::to_vec(&owner)?, 0o600)?;
            move_new(&root, &stage_name, &root, ".ken-package")?;
        }
        let meta = root.child(Path::new(".ken-package"))?;
        let owner: Owner = read_json(&meta, "owner.json")?;
        if owner.format != "ken-native-prefix/1" || !id(&owner.id) {
            return Err(invalid("foreign prefix metadata cannot be adopted"));
        }
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(meta.proc().join("lock"))?;
        if !file.metadata()?.is_file() || file.metadata()?.nlink() != 1 {
            return Err(invalid("owned lock must be a regular independent file"));
        }
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let prefix = Self {
            root,
            meta,
            owner,
            _lock: Lock(file),
        };
        prefix.root.unchanged()?;
        prefix.meta.unchanged()?;
        prefix.recover()?;
        if create {
            prefix.links()?;
        }
        Ok(Some(prefix))
    }
    fn links(&self) -> Result<()> {
        let _ = directory(&self.root, "bin")?;
        for (name, target) in LINKS {
            let (parent, leaf) = if let Some((parent, leaf)) = name.rsplit_once('/') {
                (self.root.child(Path::new(parent))?, leaf)
            } else {
                (
                    Directory {
                        file: self.root.file.try_clone()?,
                        path: self.root.path.clone(),
                    },
                    name,
                )
            };
            let path = parent.proc().join(leaf);
            if exists(&path)? {
                if fs::read_link(&path).ok().as_deref() != Some(Path::new(target)) {
                    return Err(invalid(format!("owned link was replaced: {name}")));
                }
            } else {
                symlink(target, &path)?;
                parent.file.sync_all()?;
            }
        }
        Ok(())
    }
    fn active(&self) -> Result<Option<(String, Activation)>> {
        let path = self.meta.proc().join("active");
        if !exists(&path)? {
            return Ok(None);
        }
        let target = fs::read_link(&path)?;
        let target = target
            .to_str()
            .ok_or_else(|| invalid("invalid activation pointer"))?;
        let token = target
            .strip_prefix("activations/")
            .filter(|token| id(token))
            .ok_or_else(|| invalid("unowned activation target"))?;
        let activations = self.meta.child(Path::new("activations"))?;
        let activation = activations.child(Path::new(token))?;
        let state: Activation = read_json(&activation, "state.json")?;
        if state.format != "ken-native-activation/1"
            || state.owner != self.owner.id
            || !verify::hex(&state.current)
            || state.previous.as_ref().is_some_and(|sha| !verify::hex(sha))
        {
            return Err(invalid("invalid owned activation state"));
        }
        for (name, digest) in [
            ("current", Some(&state.current)),
            ("previous", state.previous.as_ref()),
        ] {
            let link = activation.proc().join(name);
            if let Some(digest) = digest {
                let expected = format!("../../../releases/{digest}");
                if fs::read_link(link)? != Path::new(&expected) {
                    return Err(invalid("activation link differs from owned state"));
                }
            } else if exists(&link)? {
                return Err(invalid("unexpected previous activation link"));
            }
        }
        Ok(Some((token.into(), state)))
    }
    fn recover(&self) -> Result<()> {
        let transactions = directory(&self.meta, "transactions")?;
        let stages = directory(&self.meta, "staging")?;
        let activations = directory(&self.meta, "activations")?;
        let active = self.active()?.map(|(id, _)| id);
        let mut count = 0;
        for entry in fs::read_dir(transactions.proc())? {
            let entry = entry?;
            count += 1;
            if count > 1024 {
                return Err(invalid("too many pending native package transactions"));
            }
            let filename = entry
                .file_name()
                .into_string()
                .map_err(|_| invalid("invalid transaction name"))?;
            let token = filename
                .strip_suffix(".json")
                .filter(|token| id(token))
                .ok_or_else(|| invalid("unknown package transaction entry"))?;
            let record: Transaction = read_json(&transactions, &filename)?;
            if record.format != "ken-native-stage/1"
                || record.owner != self.owner.id
                || record.id != token
            {
                return Err(invalid("foreign staging receipt; preserving files"));
            }
            if exists(&stages.proc().join(token))? {
                remove_tree(&stages, token, record.stage, false)?;
            }
            if let Some((activation, identity)) = record.activation
                && active.as_deref() != Some(activation.as_str())
                && exists(&activations.proc().join(&activation))?
            {
                if !id(&activation) {
                    return Err(invalid("invalid owned activation cleanup name"));
                }
                remove_tree(&activations, &activation, identity, true)?;
            }
            fs::remove_file(transactions.proc().join(&filename))?;
            transactions.file.sync_all()?;
        }
        Ok(())
    }
    fn activate(
        &self,
        current: String,
        previous: Option<String>,
        progress: &mut impl FnMut(PackageEvent),
        transaction: Option<(&Directory, &str, &mut Transaction)>,
    ) -> Result<()> {
        self.root.unchanged()?;
        self.meta.unchanged()?;
        self.links()?;
        let original = self.active()?.map(|(token, _)| token);
        let token = nonce()?;
        let activations = directory(&self.meta, "activations")?;
        let activation = directory(&activations, &token)?;
        let state = Activation {
            format: "ken-native-activation/1".into(),
            owner: self.owner.id.clone(),
            current,
            previous,
        };
        write_new(
            &activation,
            "state.json",
            &serde_json::to_vec(&state)?,
            0o444,
        )?;
        symlink(
            format!("../../../releases/{}", state.current),
            activation.proc().join("current"),
        )?;
        if let Some(previous) = &state.previous {
            symlink(
                format!("../../../releases/{previous}"),
                activation.proc().join("previous"),
            )?;
        }
        activation.file.sync_all()?;
        activations.file.sync_all()?;
        if let Some((directory, filename, record)) = transaction {
            record.activation = Some((token.clone(), Identity::of(&activation)?));
            replace_json(directory, filename, record)?;
        }
        progress(PackageEvent::ActivationPrepared);
        if self.active()?.map(|(token, _)| token) != original {
            return Err(invalid("activation changed during publication"));
        }
        let temporary = format!(".active-{}", nonce()?);
        symlink(
            format!("activations/{token}"),
            self.meta.proc().join(&temporary),
        )?;
        fs::rename(
            self.meta.proc().join(&temporary),
            self.meta.proc().join("active"),
        )?;
        self.meta.file.sync_all()?;
        progress(PackageEvent::Activated);
        Ok(())
    }
    fn report(&self, state: &Activation, info: PackageInfo, action: &str) -> PackageReport {
        PackageReport {
            action: action.into(),
            executable: self.root.path.join("current/ken"),
            resources: self.root.path.join("current/resources/search.json"),
            release_root: self.root.path.join("releases").join(&state.current),
            current_release: state.current.clone(),
            previous_release: state.previous.clone(),
            provenance: info.provenance,
        }
    }
}
fn copy_bundle(
    source: &Path,
    target: &Directory,
    manifest: &super::model::Manifest,
    raw: &[u8],
) -> Result<()> {
    let source = Directory::open(source)?;
    for (name, record) in &manifest.files {
        let path = verify::relative(name)?;
        let mut parent = Directory {
            file: target.file.try_clone()?,
            path: target.path.clone(),
        };
        let mut parts = path.components().peekable();
        while let Some(part) = parts.next() {
            let name = part
                .as_os_str()
                .to_str()
                .ok_or_else(|| invalid("UTF8 package component required"))?;
            if parts.peek().is_some() {
                parent = directory(&parent, name)?;
            } else {
                let mut input = ken_core::source_reader::open_relative(&source.file, &path, false)?;
                let mut output = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .mode(0o600)
                    .custom_flags(libc::O_NOFOLLOW)
                    .open(parent.proc().join(name))?;
                let count = std::io::copy(
                    &mut Read::by_ref(&mut input).take(record.bytes + 1),
                    &mut output,
                )?;
                if count != record.bytes {
                    return Err(invalid("package source changed while copying"));
                }
                output.set_permissions(fs::Permissions::from_mode(record.mode))?;
                output.sync_all()?;
                parent.file.sync_all()?;
            }
        }
    }
    write_new(target, "FILES.json", raw, 0o444)?;
    source.unchanged()?;
    Ok(())
}
impl PackageApplication {
    pub fn new(prefix: &Path) -> Result<Self> {
        let prefix = std::path::absolute(prefix)?;
        if !cfg!(all(target_os = "linux", target_arch = "x86_64"))
            || prefix
                .as_os_str()
                .to_str()
                .is_none_or(|p| p.contains(['\0', ':']))
        {
            return Err(invalid(
                "Linux x86 CPU prefix with UTF8 non-colon path required",
            ));
        }
        Ok(Self { prefix })
    }
    pub fn authenticate(&self, bundle: &Path) -> Result<PackageInfo> {
        Ok(verify::authenticate(bundle)?.0)
    }
    pub fn install(&self, bundle: &Path, expected_manifest_sha256: &str) -> Result<PackageReport> {
        self.install_with_progress(bundle, expected_manifest_sha256, &mut |_| {})
    }
    pub fn install_with_progress(
        &self,
        bundle: &Path,
        expected_manifest_sha256: &str,
        progress: &mut impl FnMut(PackageEvent),
    ) -> Result<PackageReport> {
        if !verify::hex(expected_manifest_sha256) {
            return Err(invalid("expected FILES SHA256 required"));
        }
        let (info, manifest, raw) = verify::authenticate(bundle)?;
        if info.manifest_sha256 != expected_manifest_sha256 {
            return Err(invalid(
                "FILES manifest differs from explicit expected identity",
            ));
        }
        let prefix = Prefix::open(&self.prefix, true)?.expect("created prefix");
        let releases = directory(&prefix.root, "releases")?;
        let release_path = prefix
            .root
            .path
            .join("releases")
            .join(expected_manifest_sha256);
        let active = prefix.active()?;
        if exists(&releases.proc().join(expected_manifest_sha256))? {
            let existing = verify::authenticate(&release_path)?.0;
            if existing.manifest_sha256 != expected_manifest_sha256 {
                return Err(invalid("existing release identity differs"));
            }
        } else {
            let stages = directory(&prefix.meta, "staging")?;
            let transactions = directory(&prefix.meta, "transactions")?;
            let token = nonce()?;
            let stage = directory(&stages, &token)?;
            let mut record = Transaction {
                format: "ken-native-stage/1".into(),
                owner: prefix.owner.id.clone(),
                id: token.clone(),
                stage: Identity::of(&stage)?,
                activation: None,
            };
            let filename = format!("{token}.json");
            write_new(
                &transactions,
                &filename,
                &serde_json::to_vec(&record)?,
                0o600,
            )?;
            copy_bundle(bundle, &stage, &manifest, &raw)?;
            let copied = verify::authenticate(&stage.path)?.0;
            if copied.manifest_sha256 != expected_manifest_sha256 {
                return Err(invalid("copied release identity differs"));
            }
            progress(PackageEvent::StagingCopied);
            if !record.stage.matches(&stage)? {
                return Err(invalid("owned staging identity changed"));
            }
            move_new(&stages, &token, &releases, expected_manifest_sha256)?;
            progress(PackageEvent::ReleasePublished);
            let previous = active.as_ref().map(|(_, state)| state.current.clone());
            prefix.activate(
                expected_manifest_sha256.into(),
                previous,
                progress,
                Some((&transactions, &filename, &mut record)),
            )?;
            fs::remove_file(transactions.proc().join(filename))?;
            transactions.file.sync_all()?;
            let (_, state) = prefix.active()?.expect("activated state");
            return Ok(prefix.report(&state, copied, "install"));
        }
        if active
            .as_ref()
            .is_some_and(|(_, state)| state.current == expected_manifest_sha256)
        {
            return Ok(prefix.report(&active.expect("existing active").1, info, "unchanged"));
        }
        let previous = active.map(|(_, state)| state.current);
        prefix.activate(expected_manifest_sha256.into(), previous, progress, None)?;
        let (_, state) = prefix.active()?.expect("activated state");
        Ok(prefix.report(&state, info, "install"))
    }
    pub fn rollback(&self) -> Result<PackageReport> {
        let prefix = Prefix::open(&self.prefix, false)?
            .ok_or_else(|| invalid("no owned native deployment"))?;
        let (_, current) = prefix
            .active()?
            .ok_or_else(|| invalid("no active native release"))?;
        let previous = current
            .previous
            .clone()
            .ok_or_else(|| invalid("no previous native release"))?;
        let info = verify::authenticate(&prefix.root.path.join("releases").join(&previous))?.0;
        if info.manifest_sha256 != previous {
            return Err(invalid("previous release identity differs"));
        }
        prefix.activate(previous, Some(current.current), &mut |_| {}, None)?;
        let (_, state) = prefix.active()?.expect("rolled back activation");
        Ok(prefix.report(&state, info, "rollback"))
    }
    pub fn status(&self) -> Result<PackageStatus> {
        let Some(prefix) = Prefix::open(&self.prefix, false)? else {
            return Ok(PackageStatus {
                current_release: None,
                previous_release: None,
                executable: None,
                resources: None,
                release_root: None,
            });
        };
        let Some((_, state)) = prefix.active()? else {
            return Ok(PackageStatus {
                current_release: None,
                previous_release: None,
                executable: None,
                resources: None,
                release_root: None,
            });
        };
        prefix.links()?;
        Ok(PackageStatus {
            current_release: Some(state.current.clone()),
            previous_release: state.previous,
            executable: Some(prefix.root.path.join("current/ken")),
            resources: Some(prefix.root.path.join("current/resources/search.json")),
            release_root: Some(prefix.root.path.join("releases").join(state.current)),
        })
    }
}
