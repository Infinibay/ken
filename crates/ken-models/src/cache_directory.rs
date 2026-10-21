//! Anchored cache directory operations; paths cannot redirect an opened owner.
use rustix::fs::{self as at, AtFlags, Dir, FileType, Mode, OFlags, RenameFlags};
use std::{
    fs::{self, File},
    io,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
};

pub(crate) struct CacheDirectory {
    file: File,
    pub(crate) path: PathBuf,
}

fn component(name: &str) -> io::Result<()> {
    if name.is_empty() || name == "." || name == ".." || name.contains('/') || name.contains('\0') {
        return Err(io::Error::other("one cache path component required"));
    }
    Ok(())
}

impl CacheDirectory {
    pub(crate) fn root(path: &Path) -> io::Result<Self> {
        use std::os::unix::fs::DirBuilderExt;
        if !path.is_absolute() {
            return Err(io::Error::other("absolute cache root required"));
        }
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(path)?;
        let file = at::open(
            path,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )?;
        let result = Self {
            file: File::from(file),
            path: path.into(),
        };
        result.unchanged()?;
        Ok(result)
    }

    pub(crate) fn child(&self, name: &str, create: bool) -> io::Result<Self> {
        component(name)?;
        if create {
            match at::mkdirat(&self.file, name, Mode::from_bits_truncate(0o700)) {
                Ok(()) => self.sync()?,
                Err(rustix::io::Errno::EXIST) => {}
                Err(error) => return Err(error.into()),
            }
        }
        let file = at::openat(
            &self.file,
            name,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )?;
        let result = Self {
            file: File::from(file),
            path: self.path.join(name),
        };
        result.unchanged()?;
        Ok(result)
    }

    pub(crate) fn unchanged(&self) -> io::Result<()> {
        let named = fs::symlink_metadata(&self.path)?;
        let opened = self.file.metadata()?;
        if !named.is_dir()
            || named.is_symlink()
            || (named.dev(), named.ino()) != (opened.dev(), opened.ino())
        {
            return Err(io::Error::other("cache directory identity changed"));
        }
        Ok(())
    }

    pub(crate) fn create_child_exclusive(&self, name: &str) -> io::Result<Self> {
        component(name)?;
        at::mkdirat(&self.file, name, Mode::from_bits_truncate(0o700))?;
        self.child(name, false)
    }

    pub(crate) fn remove_owned_child(&self, name: &str, directory: &Self) -> io::Result<()> {
        component(name)?;
        let named = at::statat(&self.file, name, AtFlags::SYMLINK_NOFOLLOW)?;
        let opened = directory.file.metadata()?;
        if FileType::from_raw_mode(named.st_mode) != FileType::Directory
            || (named.st_dev as u64, named.st_ino as u64) != (opened.dev(), opened.ino())
        {
            return Err(io::Error::other(
                "staging name no longer belongs to this operation",
            ));
        }
        directory.remove_contents()?;
        at::unlinkat(&self.file, name, AtFlags::REMOVEDIR)?;
        self.sync()
    }

    fn remove_contents(&self) -> io::Result<()> {
        for entry in Dir::read_from(&self.file)? {
            let entry = entry?;
            let name = entry
                .file_name()
                .to_str()
                .map_err(|_| io::Error::other("invalid owned cache entry"))?;
            if name == "." || name == ".." {
                continue;
            }
            let named = at::statat(&self.file, name, AtFlags::SYMLINK_NOFOLLOW)?;
            if FileType::from_raw_mode(named.st_mode) == FileType::Directory {
                let child = self.child(name, false)?;
                self.remove_owned_child(name, &child)?;
            } else {
                at::unlinkat(&self.file, name, AtFlags::empty())?;
            }
        }
        Ok(())
    }

    pub(crate) fn create_file(&self, name: &str) -> io::Result<File> {
        component(name)?;
        Ok(File::from(at::openat(
            &self.file,
            name,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::from_bits_truncate(0o600),
        )?))
    }

    pub(crate) fn read_file(&self, name: &str) -> io::Result<File> {
        component(name)?;
        let file = File::from(at::openat(
            &self.file,
            name,
            OFlags::RDONLY | OFlags::NONBLOCK | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NOCTTY,
            Mode::empty(),
        )?);
        if !file.metadata()?.is_file() {
            return Err(io::Error::other("regular cached artifact required"));
        }
        Ok(file)
    }

    pub(crate) fn publish(&self, stage: &str, revision: &str) -> io::Result<()> {
        component(stage)?;
        component(revision)?;
        at::renameat_with(
            &self.file,
            stage,
            &self.file,
            revision,
            RenameFlags::NOREPLACE,
        )?;
        self.sync()
    }

    pub(crate) fn sync(&self) -> io::Result<()> {
        self.file.sync_all()
    }
}
