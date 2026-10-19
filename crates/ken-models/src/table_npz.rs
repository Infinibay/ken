//! Interpret self-contained table arrays; no paths or tokenizer policy here.
use crate::ModelError;
use half::f16;
use ndarray::{Array2, ShapeBuilder};
use npyz::{DType, NpyFile, Order, TypeChar};
use std::{
    collections::BTreeSet,
    io::{Cursor, Read},
};
use zip::ZipArchive;

pub(crate) fn invalid(error: impl std::fmt::Display) -> ModelError {
    ModelError::Weights(format!("static table: {error}"))
}

struct Array {
    shape: Vec<usize>,
    fortran: bool,
    bytes: Vec<u8>,
}

impl Array {
    fn npy(&self) -> Result<NpyFile<&[u8]>, ModelError> {
        NpyFile::new(self.bytes.as_slice()).map_err(invalid)
    }

    fn floats(&self, int8: bool) -> Result<Vec<f32>, ModelError> {
        let npy = self.npy()?;
        let values = match npy.dtype() {
            DType::Plain(t) => match (t.type_char(), t.size_field()) {
                (TypeChar::Int, 1) if int8 => npy
                    .into_vec::<i8>()
                    .map(|v| v.into_iter().map(f32::from).collect()),
                (TypeChar::Float, 2) => npy
                    .into_vec::<f16>()
                    .map(|v| v.into_iter().map(f16::to_f32).collect()),
                (TypeChar::Float, 4) => npy.into_vec::<f32>(),
                (TypeChar::Float, 8) => npy
                    .into_vec::<f64>()
                    .map(|v| v.into_iter().map(|x| x as f32).collect()),
                _ => return Err(invalid("unsupported numeric dtype")),
            },
            _ => return Err(invalid("plain numeric array required")),
        }
        .map_err(invalid)?;
        if values.iter().any(|x| !x.is_finite()) {
            return Err(invalid("nonfinite weights"));
        }
        Ok(values)
    }

    fn matrix(&self, int8: bool) -> Result<Array2<f32>, ModelError> {
        let [rows, cols] = self.shape.as_slice() else {
            return Err(invalid("matrix required"));
        };
        if *rows == 0 || *cols == 0 {
            return Err(invalid("nonempty matrix required"));
        }
        Array2::from_shape_vec((*rows, *cols).set_f(self.fortran), self.floats(int8)?)
            .map(|a| a.as_standard_layout().into_owned())
            .map_err(invalid)
    }

    fn byte_vector(&self) -> Result<Vec<u8>, ModelError> {
        if self.shape.len() != 1 {
            return Err(invalid("byte vector required"));
        }
        self.npy()?.into_vec::<u8>().map_err(invalid)
    }
}

pub(crate) struct Table {
    pub lut: Vec<usize>,
    pub a: Array2<f32>,
    pub b: Array2<f32>,
    pub tokenizer: Vec<u8>,
    pub meta: serde_json::Value,
}

fn read(archive: &mut ZipArchive<Cursor<&[u8]>>, name: &str) -> Result<Array, ModelError> {
    let mut entry = archive.by_name(&format!("{name}.npy")).map_err(invalid)?;
    let mut bytes = Vec::new();
    entry.read_to_end(&mut bytes).map_err(invalid)?;
    check_header(&bytes)?;
    let npy = NpyFile::new(bytes.as_slice()).map_err(invalid)?;
    let DType::Plain(dtype) = npy.dtype() else {
        return Err(invalid("plain arrays required"));
    };
    if dtype.type_char() == TypeChar::Object {
        return Err(invalid("pickle arrays forbidden"));
    }
    let shape: Vec<usize> = npy
        .shape()
        .iter()
        .map(|n| usize::try_from(*n).map_err(invalid))
        .collect::<Result<_, _>>()?;
    let count = shape
        .iter()
        .try_fold(1usize, |a, b| a.checked_mul(*b))
        .ok_or_else(|| invalid("shape overflow"))?;
    let payload = count
        .checked_mul(usize::try_from(dtype.size_field()).map_err(invalid)?)
        .ok_or_else(|| invalid("array size overflow"))?;
    if payload > bytes.len() {
        return Err(invalid("truncated array"));
    }
    let fortran = npy.order() == Order::Fortran;
    Ok(Array {
        shape,
        fortran,
        bytes,
    })
}

// npyz 0.9.1 computes shape products unchecked. Validate the small literal
// header before handing it to that reader, so corrupt dimensions return Err.
fn check_header(bytes: &[u8]) -> Result<(), ModelError> {
    use py_literal::Value;
    if bytes.get(..6) != Some(b"\x93NUMPY") || bytes.get(7) != Some(&0) {
        return Err(invalid("invalid NPY header"));
    }
    let (offset, length) = match bytes.get(6) {
        Some(1) => (
            10usize,
            u16::from_le_bytes(
                bytes
                    .get(8..10)
                    .ok_or_else(|| invalid("truncated header"))?
                    .try_into()
                    .map_err(invalid)?,
            ) as usize,
        ),
        Some(2 | 3) => (
            12usize,
            u32::from_le_bytes(
                bytes
                    .get(8..12)
                    .ok_or_else(|| invalid("truncated header"))?
                    .try_into()
                    .map_err(invalid)?,
            ) as usize,
        ),
        _ => return Err(invalid("unsupported NPY version")),
    };
    let end = offset
        .checked_add(length)
        .ok_or_else(|| invalid("header overflow"))?;
    let text = std::str::from_utf8(
        bytes
            .get(offset..end)
            .ok_or_else(|| invalid("truncated header"))?,
    )
    .map_err(invalid)?;
    let Value::Dict(fields) = text.trim().parse::<Value>().map_err(invalid)? else {
        return Err(invalid("header dict required"));
    };
    let mut names = BTreeSet::new();
    for (key, _) in &fields {
        let Value::String(name) = key else {
            return Err(invalid("header keys must be strings"));
        };
        if !names.insert(name) {
            return Err(invalid(format!("duplicate NPY header key: {name}")));
        }
    }
    let field = |name: &str| {
        fields
            .iter()
            .find_map(|(key, value)| matches!(key,Value::String(s) if s==name).then_some(value))
            .ok_or_else(|| invalid(format!("missing {name}")))
    };
    let Value::Tuple(shape) = field("shape")? else {
        return Err(invalid("shape tuple required"));
    };
    if shape.len() > 2 {
        return Err(invalid("vector or matrix required"));
    }
    let dims: Vec<usize> = shape
        .iter()
        .map(|v| match v {
            Value::Integer(n) => n.to_string().parse::<usize>().map_err(invalid),
            _ => Err(invalid("nonnegative dimensions required")),
        })
        .collect::<Result<_, _>>()?;
    let mut count = 1usize;
    let mut reverse = 1usize;
    for (a, b) in dims.iter().zip(dims.iter().rev()) {
        count = count
            .checked_mul(*a)
            .ok_or_else(|| invalid("shape overflow"))?;
        reverse = reverse
            .checked_mul(*b)
            .ok_or_else(|| invalid("stride overflow"))?;
    }
    let Value::String(dtype) = field("descr")? else {
        return Err(invalid("plain dtype required"));
    };
    let dtype = dtype.parse::<npyz::TypeStr>().map_err(invalid)?;
    let size = usize::try_from(dtype.size_field()).map_err(invalid)?;
    if count.checked_mul(size) != Some(bytes.len() - end) {
        return Err(invalid("array payload does not match shape"));
    }
    Ok(())
}

impl Table {
    pub fn from_npz(bytes: &[u8]) -> Result<Self, ModelError> {
        let mut archive = ZipArchive::new(Cursor::new(bytes)).map_err(invalid)?;
        let mut names = BTreeSet::new();
        for i in 0..archive.len() {
            let entry = archive.by_index(i).map_err(invalid)?;
            if !names.insert(entry.name().to_owned()) {
                return Err(invalid("duplicate array"));
            }
        }
        let raw_a = read(&mut archive, "A")?;
        let is_int8 = matches!(raw_a.npy()?.dtype(),DType::Plain(t) if t.type_char()==TypeChar::Int && t.size_field()==1);
        let mut a = raw_a.matrix(true)?;
        if is_int8 {
            let scales = read(&mut archive, "A_scale")?;
            if scales.shape != [a.nrows()] {
                return Err(invalid("one scale per row required"));
            }
            let scales = scales.floats(false)?;
            for (mut row, scale) in a.rows_mut().into_iter().zip(scales) {
                row *= scale;
            }
            if a.iter().any(|x| !x.is_finite()) {
                return Err(invalid("nonfinite dequantized weights"));
            }
        }
        let b = read(&mut archive, "B")?.matrix(false)?;
        if a.ncols() != b.nrows() {
            return Err(invalid("projection rank mismatch"));
        }
        let raw_lut = read(&mut archive, "lut")?;
        if raw_lut.shape.len() != 1 {
            return Err(invalid("one dimensional LUT required"));
        }
        let npy = raw_lut.npy()?;
        let lut: Vec<i64> = match npy.dtype() {
            DType::Plain(t) => match (t.type_char(), t.size_field()) {
                (TypeChar::Int, 4) => npy
                    .into_vec::<i32>()
                    .map(|v| v.into_iter().map(i64::from).collect()),
                (TypeChar::Int, 8) => npy.into_vec::<i64>(),
                _ => return Err(invalid("int32/int64 LUT required")),
            },
            _ => return Err(invalid("plain LUT required")),
        }
        .map_err(invalid)?;
        let rows = i64::try_from(a.nrows()).map_err(invalid)?;
        let lut = lut
            .into_iter()
            .map(|i| {
                let i = if i < 0 {
                    i.checked_add(rows).ok_or_else(|| invalid("LUT overflow"))?
                } else {
                    i
                };
                if !(0..rows).contains(&i) {
                    return Err(invalid("LUT outside table rows"));
                }
                Ok(i as usize)
            })
            .collect::<Result<_, ModelError>>()?;
        let tokenizer = read(&mut archive, "tokenizer")?.byte_vector()?;
        let meta = serde_json::from_slice(&read(&mut archive, "meta")?.byte_vector()?)?;
        if !matches!(meta, serde_json::Value::Object(_)) {
            return Err(invalid("metadata object required"));
        }
        Ok(Self {
            lut,
            a,
            b,
            tokenizer,
            meta,
        })
    }
}
