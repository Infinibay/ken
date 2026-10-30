//! Decode a checked-in historical JSON fixture; no archive/runtime discovery.
use std::io::Read;
pub fn decode(compressed: &[u8]) -> Vec<u8> {
    let mut bytes = Vec::new();
    flate2::read::GzDecoder::new(compressed)
        .read_to_end(&mut bytes)
        .expect("complete vendored historical fixture");
    bytes
}
