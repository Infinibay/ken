//! A private glibc namespace with authenticated dependencies bound before users.
//!
//! A bare NEWLM is insufficient: LD_LIBRARY_PATH still precedes DT_RUNPATH.
//! Explicit absolute loads in dependency order pin each owned SONAME first.
use super::{Dependencies, invalid};
use crate::ModelError;
use libloading::Library;
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::{CStr, CString},
    fs::File,
    io::{Read, Seek, SeekFrom},
    os::unix::ffi::OsStrExt,
    path::{Path, PathBuf},
};

struct Elf {
    soname: Option<String>,
    needed: Vec<String>,
}

struct Image {
    file: File,
    bytes: u64,
}

impl Image {
    fn read<const N: usize>(&mut self, offset: u64) -> Result<[u8; N], ModelError> {
        self.range(offset, N as u64)?;
        self.file.seek(SeekFrom::Start(offset)).map_err(invalid)?;
        let mut bytes = [0; N];
        self.file.read_exact(&mut bytes).map_err(invalid)?;
        Ok(bytes)
    }

    fn range(&self, offset: u64, size: u64) -> Result<(), ModelError> {
        if offset.checked_add(size).is_none_or(|end| end > self.bytes) {
            return Err(invalid("native ELF range outside authenticated file"));
        }
        Ok(())
    }

    fn name(&mut self, table: u64, size: u64, index: u64) -> Result<String, ModelError> {
        if index >= size {
            return Err(invalid("native ELF string outside dynamic string table"));
        }
        self.file
            .seek(SeekFrom::Start(add(table, index)?))
            .map_err(invalid)?;
        let mut value = Vec::new();
        for _ in index..size {
            let mut byte = [0];
            self.file.read_exact(&mut byte).map_err(invalid)?;
            if byte[0] == 0 {
                let name = String::from_utf8(value).map_err(invalid)?;
                if name.is_empty()
                    || name.contains('/')
                    || name.contains('\\')
                    || name.contains(':')
                {
                    return Err(invalid("native ELF dependency must be a basename"));
                }
                return Ok(name);
            }
            // Linux path components cannot exceed NAME_MAX; a bounded parser
            // must not allocate according to an untrusted dynamic string size.
            if value.len() == 255 {
                return Err(invalid("native ELF dependency name exceeds NAME_MAX"));
            }
            value.push(byte[0]);
        }
        Err(invalid("unterminated native ELF dependency name"))
    }
}

fn add(a: u64, b: u64) -> Result<u64, ModelError> {
    a.checked_add(b)
        .ok_or_else(|| invalid("native ELF offset overflow"))
}

fn u64_at(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(
        bytes[offset..offset + 8]
            .try_into()
            .expect("fixed ELF field"),
    )
}

fn elf(path: &Path) -> Result<Elf, ModelError> {
    let file = File::open(path).map_err(invalid)?;
    let bytes = file.metadata().map_err(invalid)?.len();
    let mut image = Image { file, bytes };
    let header = image.read::<64>(0)?;
    if &header[..6] != b"\x7fELF\x02\x01" {
        return Err(invalid(
            "isolated native core requires a little-endian ELF64 image",
        ));
    }
    let offset = u64_at(&header, 32);
    let stride = u16::from_le_bytes([header[54], header[55]]) as u64;
    let count = u16::from_le_bytes([header[56], header[57]]) as u64;
    if stride < 56 || count == 0 || count == 0xffff {
        return Err(invalid("unsupported native ELF program header table"));
    }
    image.range(offset, stride * count)?;
    let mut loads = Vec::new();
    let mut dynamic = None;
    for index in 0..count {
        let entry = image.read::<56>(add(offset, stride * index)?)?;
        let kind = u32::from_le_bytes(entry[..4].try_into().expect("ELF segment kind"));
        let file_offset = u64_at(&entry, 8);
        let address = u64_at(&entry, 16);
        let size = u64_at(&entry, 32);
        if kind == 1 || kind == 2 {
            image.range(file_offset, size)?;
        }
        match kind {
            1 => loads.push((address, file_offset, size)),
            2 if dynamic.replace((file_offset, size)).is_some() => {
                return Err(invalid("duplicate native ELF dynamic segment"));
            }
            _ => {}
        }
    }
    let (offset, size) = dynamic.ok_or_else(|| invalid("native ELF has no dynamic segment"))?;
    let mut table = None;
    let mut table_size = None;
    let mut soname = None;
    let mut needed = Vec::new();
    let mut terminated = false;
    for index in 0..size / 16 {
        let entry = image.read::<16>(add(offset, index * 16)?)?;
        let value = u64_at(&entry, 8);
        match u64_at(&entry, 0) {
            0 => {
                terminated = true;
                break;
            }
            1 => needed.push(value),
            5 => table = Some(value),
            10 => table_size = Some(value),
            14 => soname = Some(value),
            _ => {}
        }
    }
    if !terminated {
        return Err(invalid("unterminated native ELF dynamic segment"));
    }
    let table = table.ok_or_else(|| invalid("native ELF has no dynamic string table"))?;
    let size = table_size.ok_or_else(|| invalid("native ELF has no dynamic string size"))?;
    let offset = loads
        .into_iter()
        .find_map(|(address, offset, length)| {
            let relative = table.checked_sub(address)?;
            (relative.checked_add(size)? <= length)
                .then(|| offset.checked_add(relative))
                .flatten()
        })
        .ok_or_else(|| invalid("native ELF dynamic strings are not file-backed"))?;
    image.range(offset, size)?;
    Ok(Elf {
        soname: soname
            .map(|index| image.name(offset, size, index))
            .transpose()?,
        needed: needed
            .into_iter()
            .map(|index| image.name(offset, size, index))
            .collect::<Result<_, _>>()?,
    })
}

fn visit(
    name: &str,
    images: &BTreeMap<String, (PathBuf, Elf)>,
    visiting: &mut BTreeSet<String>,
    visited: &mut BTreeSet<String>,
    order: &mut Vec<PathBuf>,
) -> Result<(), ModelError> {
    if visited.contains(name) {
        return Ok(());
    }
    if visiting.len() >= 128 {
        return Err(invalid(
            "private native dependency graph exceeds 128 loading steps",
        ));
    }
    if !visiting.insert(name.to_owned()) {
        return Err(invalid("cycle in authenticated native dependency closure"));
    }
    let (path, image) = &images[name];
    for dependency in &image.needed {
        if images.contains_key(dependency) {
            visit(dependency, images, visiting, visited, order)?;
        }
    }
    visiting.remove(name);
    visited.insert(name.to_owned());
    order.push(path.clone());
    Ok(())
}

fn ordered<'a>(
    module: &Path,
    root: &Path,
    names: impl Iterator<Item = &'a String>,
) -> Result<Vec<PathBuf>, ModelError> {
    let mut images = BTreeMap::new();
    for relative in names {
        let path = root.join(relative);
        let image = elf(&path)?;
        let name = image.soname.clone().unwrap_or_else(|| {
            path.file_name()
                .expect("validated relative library")
                .to_string_lossy()
                .into_owned()
        });
        if images.insert(name, (path, image)).is_some() {
            return Err(invalid(
                "ambiguous SONAME in authenticated native dependency closure",
            ));
        }
    }
    let module_image = elf(module)?;
    if module_image
        .soname
        .as_ref()
        .is_some_and(|name| images.contains_key(name))
    {
        return Err(invalid(
            "native module SONAME aliases an authenticated dependency",
        ));
    }
    let mut order = Vec::new();
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for name in images.keys() {
        visit(name, &images, &mut visiting, &mut visited, &mut order)?;
    }
    Ok(order)
}

fn loader_error(context: &str) -> ModelError {
    // SAFETY: dlerror returns a thread-local NUL-terminated string until the
    // next loader call; copy it immediately, without any intervening call.
    let detail = unsafe {
        let error = libc::dlerror();
        if error.is_null() {
            "unknown glibc loader failure".to_owned()
        } else {
            CStr::from_ptr(error).to_string_lossy().into_owned()
        }
    };
    invalid(format!("{context}: {detail}"))
}

fn open(namespace: libc::Lmid_t, path: &Path) -> Result<Library, ModelError> {
    let path = CString::new(path.as_os_str().as_bytes()).map_err(invalid)?;
    // SAFETY: each path is an authenticated private ELF file. The newly owned
    // handle is closed by libloading; no API or object escapes its owner.
    let handle =
        unsafe { libc::dlmopen(namespace, path.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL) };
    if handle.is_null() {
        return Err(loader_error("isolated native core dlmopen"));
    }
    Ok(unsafe { libloading::os::unix::Library::from_raw(handle) }.into())
}

pub(super) fn load<'a>(
    module: &Path,
    root: &Path,
    names: impl Iterator<Item = &'a String>,
) -> Result<(Library, Dependencies), ModelError> {
    let order = ordered(module, root, names)?;
    let mut dependencies = Dependencies(Vec::new());
    let first = order
        .first()
        .ok_or_else(|| invalid("isolated native core has no dependencies"))?;
    let first = open(libc::LM_ID_NEWLM, first)?;
    // libloading owns the handle, but dlinfo only borrows it. Conversion to the
    // platform owner and back retains exactly one dlclose responsibility.
    let platform: libloading::os::unix::Library = first.into();
    let handle = platform.into_raw();
    let mut namespace: libc::Lmid_t = libc::LM_ID_NEWLM;
    let status = unsafe {
        libc::dlinfo(
            handle,
            libc::RTLD_DI_LMID,
            (&mut namespace as *mut libc::Lmid_t).cast(),
        )
    };
    let first: Library = unsafe { libloading::os::unix::Library::from_raw(handle) }.into();
    dependencies.0.push(first);
    if status != 0 {
        return Err(loader_error("isolated native core namespace identity"));
    }
    if namespace == libc::LM_ID_BASE || namespace == libc::LM_ID_NEWLM {
        return Err(invalid(
            "glibc did not create an isolated native core namespace",
        ));
    }
    for path in order.iter().skip(1) {
        dependencies.0.push(open(namespace, path)?);
    }
    Ok((open(namespace, module)?, dependencies))
}
