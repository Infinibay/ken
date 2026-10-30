//! JSON layout changes preserve numerical spellings and Python string values.
pub fn compact(input: &str) -> serde_json::Result<String> {
    let _: Box<serde_json::value::RawValue> = serde_json::from_str(input)?;
    let mut output = Vec::with_capacity(input.len());
    let (mut quoted, mut escaped) = (false, false);
    for byte in input.bytes() {
        if quoted {
            output.push(byte);
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
            }
        } else if byte == b'"' {
            quoted = true;
            output.push(byte);
        } else if !matches!(byte, b' ' | b'\t' | b'\r' | b'\n') {
            output.push(byte);
        }
    }
    Ok(String::from_utf8(output).expect("removing JSON ASCII layout preserves UTF8"))
}
#[cfg(test)]
mod tests {
    #[test]
    fn compaction_preserves_opaque_strings_and_arbitrary_numbers() {
        let input = " { \"value\" : [ \"\\ud800\", 1e1000, -0.0, \"á a \\\" b\" ] } \n";
        assert_eq!(
            super::compact(input).unwrap(),
            "{\"value\":[\"\\ud800\",1e1000,-0.0,\"á a \\\" b\"]}"
        );
        assert!(super::compact("[1,]").is_err());
        assert!(super::compact("{} extra").is_err());
    }
}
