//! Immutable published NPY ownership; all mapping geometry is checked in one place.
use crate::{Result, context_vector_cache::invalid};
use npyz::{DType, Endianness, NpyFile, Order, TypeChar};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    os::fd::AsRawFd,
    path::Path,
    ptr::NonNull,
};
const MAX_HEADER: usize = 1024 * 1024;
fn io(error: impl std::fmt::Display) -> crate::RetrievalError {
    invalid(format!("context matrix artifact: {error}"))
}
fn digest(file: &mut File) -> Result<String> {
    file.seek(SeekFrom::Start(0)).map_err(io)?;
    let mut h = Sha256::new();
    let mut buffer = [0; 65536];
    loop {
        let n = file.read(&mut buffer).map_err(io)?;
        if n == 0 {
            break;
        }
        h.update(&buffer[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}
pub(crate) fn file_sha(path: &Path) -> Result<String> {
    digest(&mut File::open(path).map_err(io)?)
}
#[derive(Debug)]
pub(crate) struct MappedNpy {
    _file: File,
    address: NonNull<libc::c_void>,
    length: usize,
    offset: usize,
    rows: usize,
    width: usize,
}
// Published snapshot files are application-owned and immutable. Readers retain the
// mapping/inode across atomic replacement; no mutable address escapes this owner.
unsafe impl Send for MappedNpy {}
unsafe impl Sync for MappedNpy {}
impl MappedNpy {
    /// Caller owns the immutable publication contract: do not truncate or modify
    /// this inode in place while any returned matrix is alive.
    pub(crate) unsafe fn open(path: &Path, sha: &str, rows: usize, width: usize) -> Result<Self> {
        if !cfg!(target_endian = "little") {
            return Err(io("little-endian matrix host required"));
        }
        let elements = rows
            .checked_mul(width)
            .filter(|&n| n > 0)
            .ok_or_else(|| io("invalid matrix dimensions"))?;
        let data_bytes = elements
            .checked_mul(4)
            .ok_or_else(|| io("matrix size overflow"))?;
        let mut file = File::open(path).map_err(io)?;
        let length = usize::try_from(file.metadata().map_err(io)?.len()).map_err(io)?;
        if length > isize::MAX as usize
            || length
                > data_bytes
                    .checked_add(MAX_HEADER)
                    .ok_or_else(|| io("matrix size overflow"))?
        {
            return Err(io("matrix artifact size differs"));
        }
        if digest(&mut file)? != sha {
            return Err(invalid(
                "context artifact hash mismatch; remove this snapshot and prepare again",
            ));
        }
        file.seek(SeekFrom::Start(0)).map_err(io)?;
        let mut prefix = [0; 12];
        file.read_exact(&mut prefix[..8]).map_err(io)?;
        let prefix_length = match &prefix[..8] {
            b"\x93NUMPY\x01\x00" => 10,
            b"\x93NUMPY\x02\x00" | b"\x93NUMPY\x03\x00" => 12,
            _ => return Err(io("invalid NPY header")),
        };
        file.read_exact(&mut prefix[8..prefix_length]).map_err(io)?;
        let header_length = if prefix_length == 10 {
            u16::from_le_bytes(prefix[8..10].try_into().expect("two bytes")) as usize
        } else {
            u32::from_le_bytes(prefix[8..12].try_into().expect("four bytes")) as usize
        };
        if header_length > MAX_HEADER
            || header_length
                .checked_add(prefix_length)
                .is_none_or(|n| n > length)
        {
            return Err(io("NPY header exceeds artifact"));
        }
        file.seek(SeekFrom::Start(0)).map_err(io)?;
        let npy = NpyFile::new(&mut file).map_err(io)?;
        if npy.shape() != [rows as u64, width as u64] || npy.order() != Order::C {
            return Err(io("NPY matrix shape/order differs"));
        }
        if !matches!(npy.dtype(),DType::Plain(t)if t.type_char()==TypeChar::Float&&t.size_field()==4&&t.endianness()==Endianness::Little)
        {
            return Err(io("little-endian float32 NPY required"));
        }
        let offset =
            usize::try_from(npy.into_inner().stream_position().map_err(io)?).map_err(io)?;
        if !offset.is_multiple_of(std::mem::align_of::<f32>())
            || offset.checked_add(data_bytes) != Some(length)
        {
            return Err(io("NPY payload size/alignment differs"));
        }
        // SAFETY: fd is open/readable, nonzero checked length fits isize, offset and
        // payload geometry match the file; publication immutability is caller-owned.
        let raw = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                length,
                libc::PROT_READ,
                libc::MAP_PRIVATE,
                file.as_raw_fd(),
                0,
            )
        };
        if raw == libc::MAP_FAILED {
            return Err(io(std::io::Error::last_os_error()));
        }
        let address = NonNull::new(raw).ok_or_else(|| io("null matrix mapping"))?;
        Ok(Self {
            _file: file,
            address,
            length,
            offset,
            rows,
            width,
        })
    }
    pub(crate) fn rows(&self) -> usize {
        self.rows
    }
    pub(crate) fn width(&self) -> usize {
        self.width
    }
    pub(crate) fn values(&self) -> &[f32] {
        // SAFETY: open checked alignment/extent and all f32 bit patterns are valid;
        // owner retains this read-only mapping and file for the slice lifetime.
        unsafe {
            std::slice::from_raw_parts(
                self.address
                    .as_ptr()
                    .cast::<u8>()
                    .add(self.offset)
                    .cast::<f32>(),
                self.rows * self.width,
            )
        }
    }
    pub(crate) fn row(&self, index: usize) -> Result<&[f32]> {
        if index >= self.rows {
            return Err(io("matrix row outside artifact"));
        }
        Ok(&self.values()[index * self.width..(index + 1) * self.width])
    }
}
impl Drop for MappedNpy {
    fn drop(&mut self) {
        // SAFETY: this owner unmaps exactly its original mapping once, after borrows end.
        let _ = unsafe { libc::munmap(self.address.as_ptr(), self.length) };
    }
}
pub(crate) struct NpyWriter {
    file: File,
    rows: usize,
    width: usize,
    written: usize,
}
impl NpyWriter {
    pub(crate) fn create(path: &Path, rows: usize, width: usize) -> Result<Self> {
        if rows == 0 || width == 0 {
            return Err(io("nonempty matrix required"));
        }
        let mut header =
            format!("{{'descr': '<f4', 'fortran_order': False, 'shape': ({rows}, {width}), }}");
        let padding = (64 - (10 + header.len() + 1) % 64) % 64;
        header.extend(std::iter::repeat_n(' ', padding));
        header.push('\n');
        let length = u16::try_from(header.len()).map_err(io)?;
        let mut file = File::create(path).map_err(io)?;
        file.write_all(b"\x93NUMPY\x01\x00").map_err(io)?;
        file.write_all(&length.to_le_bytes()).map_err(io)?;
        file.write_all(header.as_bytes()).map_err(io)?;
        Ok(Self {
            file,
            rows,
            width,
            written: 0,
        })
    }
    pub(crate) fn row(&mut self, values: &[f32]) -> Result<()> {
        if values.len() != self.width || self.written >= self.rows {
            return Err(io("matrix writer row count/dimension differs"));
        }
        let b = values
            .iter()
            .flat_map(|v| v.to_le_bytes())
            .collect::<Vec<_>>();
        self.file.write_all(&b).map_err(io)?;
        self.written += 1;
        Ok(())
    }
    pub(crate) fn finish(mut self) -> Result<()> {
        if self.written != self.rows {
            return Err(io("incomplete matrix artifact"));
        }
        self.file.flush().map_err(io)?;
        Ok(())
    }
}
