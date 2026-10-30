//! Python source-byte decoding: PEP263 cookies, UTF8 BOM, and strict native
//! iconv conversion. Codec aliases are Python3.12 definition data, not code.
use std::{collections::BTreeMap, fmt, sync::OnceLock};
#[derive(Debug)]
pub struct SourceDecodeError {
    kind: &'static str,
    message: String,
}
impl SourceDecodeError {
    pub fn kind(&self) -> &'static str {
        self.kind
    }
}
impl fmt::Display for SourceDecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for SourceDecodeError {}
fn error(kind: &'static str, message: impl Into<String>) -> SourceDecodeError {
    SourceDecodeError {
        kind,
        message: message.into(),
    }
}
fn aliases() -> &'static BTreeMap<String, String> {
    #[derive(serde::Deserialize)]
    struct Definition {
        aliases: BTreeMap<String, String>,
    }
    static TABLE: OnceLock<Definition> = OnceLock::new();
    &TABLE
        .get_or_init(|| {
            serde_json::from_str(include_str!("../resources/python312-codec-aliases.json"))
                .expect("Python3.12 codec alias definition")
        })
        .aliases
}
fn canonical(name: &str) -> String {
    let prefix = name
        .chars()
        .take(12)
        .collect::<String>()
        .to_ascii_lowercase()
        .replace('_', "-");
    if prefix == "utf-8" || prefix.starts_with("utf-8-") {
        return "utf_8".into();
    }
    if ["latin-1", "iso-8859-1", "iso-latin-1"]
        .iter()
        .any(|p| prefix == *p || prefix.starts_with(&format!("{p}-")))
    {
        return "latin_1".into();
    }
    let normalized = name.to_ascii_lowercase().replace('-', "_");
    aliases().get(&normalized).cloned().unwrap_or(normalized)
}
fn cookie(line: &[u8]) -> Result<Option<String>, SourceDecodeError> {
    let line = std::str::from_utf8(line)
        .map_err(|_| error("SyntaxError", "invalid or missing encoding declaration"))?;
    let bytes = line.as_bytes();
    let start = bytes
        .iter()
        .take_while(|c| matches!(**c, b' ' | b'\t' | 12))
        .count();
    if bytes.get(start) != Some(&b'#') {
        return Ok(None);
    }
    for index in start..bytes.len() {
        if !bytes[index..].starts_with(b"coding") {
            continue;
        }
        let mut at = index + 6;
        if !bytes.get(at).is_some_and(|b| matches!(*b, b':' | b'=')) {
            continue;
        }
        at += 1;
        while bytes.get(at).is_some_and(|b| matches!(*b, b' ' | b'\t')) {
            at += 1;
        }
        let end = at
            + bytes[at..]
                .iter()
                .take_while(|b| b.is_ascii_alphanumeric() || matches!(**b, b'_' | b'-' | b'.'))
                .count();
        if end > at {
            return Ok(Some(canonical(&line[at..end])));
        }
    }
    Ok(None)
}
fn blank(line: &[u8]) -> bool {
    let at = line
        .iter()
        .take_while(|c| matches!(**c, b' ' | b'\t' | 12))
        .count();
    line.get(at)
        .is_none_or(|b| matches!(*b, b'#' | b'\r' | b'\n'))
}
pub fn decode_python(bytes: &[u8]) -> Result<String, SourceDecodeError> {
    let bom = bytes.starts_with(&[0xef, 0xbb, 0xbf]);
    let data = if bom { &bytes[3..] } else { bytes };
    let mut lines = data.split_inclusive(|b| *b == b'\n');
    let first = lines.next().unwrap_or(&[]);
    let mut encoding = cookie(first)?;
    if encoding.is_none() && blank(first) {
        encoding = cookie(lines.next().unwrap_or(&[]))?;
    }
    let encoding = encoding.unwrap_or_else(|| "utf_8".into());
    if bom && encoding != "utf_8" {
        return Err(error("SyntaxError", "encoding problem: utf-8"));
    }
    if encoding == "utf_8" {
        return std::str::from_utf8(data)
            .map(str::to_owned)
            .map_err(|e| error("UnicodeDecodeError", e.to_string()));
    }
    // Only Python's registered source-codec names are admitted. iconv aliases
    // alone must not accidentally broaden the Python public input contract.
    if encoding != "ascii"
        && encoding != "latin_1"
        && !aliases().values().any(|name| name == &encoding)
    {
        return Err(error(
            "SyntaxError",
            format!("unknown encoding: {encoding}"),
        ));
    }
    convert(data, &encoding)
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn convert(data: &[u8], encoding: &str) -> Result<String, SourceDecodeError> {
    use std::ffi::{CString, c_char, c_void};
    unsafe extern "C" {
        fn iconv_open(to: *const c_char, from: *const c_char) -> *mut c_void;
        fn iconv(
            cd: *mut c_void,
            input: *mut *mut c_char,
            input_left: *mut usize,
            output: *mut *mut c_char,
            output_left: *mut usize,
        ) -> usize;
        fn iconv_close(cd: *mut c_void) -> libc::c_int;
    }
    struct Decoder(*mut c_void);
    impl Drop for Decoder {
        fn drop(&mut self) {
            unsafe {
                iconv_close(self.0);
            }
        }
    }
    let iconv_name = match encoding {
        "latin_1" => "ISO-8859-1".into(),
        "utf_8_sig" => "UTF-8".into(),
        "shift_jis" => "SHIFT-JIS".into(),
        name => name.replace('_', "-"),
    };
    let name =
        CString::new(iconv_name).map_err(|_| error("SyntaxError", "invalid encoding name"))?;
    let pointer = unsafe { iconv_open(c"UTF-8".as_ptr(), name.as_ptr()) };
    if pointer as usize == usize::MAX {
        return Err(error(
            "LookupError",
            format!("native source codec unavailable: {encoding}"),
        ));
    }
    let decoder = Decoder(pointer);
    let capacity = data
        .len()
        .checked_mul(4)
        .and_then(|n| n.checked_add(32))
        .ok_or_else(|| error("UnicodeDecodeError", "source decode size overflow"))?;
    let mut output = Vec::new();
    output
        .try_reserve_exact(capacity)
        .map_err(|_| error("UnicodeDecodeError", "source decode allocation failed"))?;
    output.resize(capacity, 0);
    let mut input = data.as_ptr() as *mut c_char;
    let mut input_left = data.len();
    let mut out = output.as_mut_ptr() as *mut c_char;
    let mut left = capacity;
    let result = unsafe { iconv(decoder.0, &mut input, &mut input_left, &mut out, &mut left) };
    if result == usize::MAX {
        return Err(error(
            "UnicodeDecodeError",
            format!(
                "invalid {encoding} source at byte {}: {}",
                data.len() - input_left,
                std::io::Error::last_os_error()
            ),
        ));
    }
    if input_left != 0 {
        return Err(error(
            "UnicodeDecodeError",
            "native source decoder did not consume input",
        ));
    }
    output.truncate(capacity - left);
    String::from_utf8(output).map_err(|e| error("UnicodeDecodeError", e.to_string()))
}
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn convert(_: &[u8], encoding: &str) -> Result<String, SourceDecodeError> {
    Err(error(
        "LookupError",
        format!("native source codec {encoding} is unqualified on this platform"),
    ))
}
