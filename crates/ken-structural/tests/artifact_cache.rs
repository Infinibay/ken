//! Cache format compatibility, corruption recovery and page-budget boundaries.
use ken_store::artifact_cache::ArtifactCache;
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
#[test]
fn original_cache_opens_and_json_and_ir_remain_lossless() {
    let bytes = include_bytes!("original-cache.sqlite");
    assert_eq!(bytes.len(), 20480);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "f01935d7c0cb70d02289b7b5ad87b819278933352c967dec5327985b988651db"
    );
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("cache.sqlite");
    std::fs::write(&path, bytes).unwrap();
    let mut cache = ArtifactCache::open(&path, 2.).unwrap();
    assert!(cache.stats().enabled, "{:?}", cache.stats());
    assert_eq!(cache.get_ir("portable").unwrap().path, "cache.py");
    let text = format!(
        r#"{{"surrogate":"\ud800","number":1e400,"nested":{}0{}}}"#,
        "[".repeat(150),
        "]".repeat(150)
    );
    let raw = RawValue::from_string(text.clone()).unwrap();
    cache.put_json("opaque", &raw);
    assert_eq!(cache.get_json("opaque").unwrap().get(), text);
    drop(cache);
    let mut reopened = ArtifactCache::open(&path, 2.).unwrap();
    assert_eq!(reopened.get_json("opaque").unwrap().get(), text);
    assert_eq!(reopened.stats().hits, 1);
}
#[test]
fn invalid_entries_are_misses_foreign_databases_stay_untouched_and_disabled_cache_creates_nothing()
{
    let temp = tempfile::tempdir().unwrap();
    let foreign = temp.path().join("foreign.sqlite");
    let db = rusqlite::Connection::open(&foreign).unwrap();
    db.execute_batch("CREATE TABLE notes(secret TEXT); INSERT INTO notes VALUES('retain');")
        .unwrap();
    drop(db);
    let before = std::fs::read(&foreign).unwrap();
    let cache = ArtifactCache::open(&foreign, 1.).unwrap();
    assert!(!cache.stats().enabled);
    assert!(cache.stats().error.is_some());
    assert_eq!(std::fs::read(&foreign).unwrap(), before);
    let absent = temp.path().join("absent/cache.sqlite");
    let mut disabled = ArtifactCache::open(&absent, 0.02).unwrap();
    assert!(!disabled.stats().enabled);
    assert!(disabled.get_json("none").is_none());
    disabled.put_json("unused", &RawValue::from_string("{}".into()).unwrap());
    assert!(!absent.parent().unwrap().exists());
    for limit in [-1., f64::NAN, f64::INFINITY] {
        assert!(ArtifactCache::open(&absent, limit).is_err());
    }
    let path = temp.path().join("corrupt.sqlite");
    let mut cache = ArtifactCache::open(&path, 1.).unwrap();
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute(
        "INSERT INTO entries VALUES(?1,?2,?3,?4)",
        rusqlite::params!["bad", b"invalid zlib", 12, 1],
    )
    .unwrap();
    assert!(cache.get_json("bad").is_none());
    assert_eq!(cache.stats().misses, 1);
    cache.put_json("bad", &RawValue::from_string("{}".into()).unwrap());
    assert!(cache.get_ir("bad").is_none());
    assert_eq!(cache.stats().misses, 2);
    assert_eq!(cache.stats().hits, 0);
    assert_eq!(
        cache.stats().error.as_deref(),
        Some("invalid cached IR; rebuilding")
    );
}
#[test]
fn transactional_lru_caps_pages_and_touches_preserve_recent_entries() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("cache.sqlite");
    let mut cache = ArtifactCache::open(&path, 0.10).unwrap();
    let mut state = 9u64;
    let mut text = String::new();
    for _ in 0..24000 {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        text.push(char::from(b'a' + ((state >> 32) % 26) as u8));
    }
    let raw = RawValue::from_string(serde_json::to_string(&text).unwrap()).unwrap();
    for i in 0..8 {
        cache.put_json(&format!("key-{i}"), &raw);
        assert!(cache.stats().enabled);
        assert!(cache.stats().error.is_none(), "{:?}", cache.stats());
        assert!(cache.stats().bytes <= cache.stats().max_bytes);
    }
    assert!(cache.stats().evictions > 0);
    assert!(cache.get_json("key-7").is_some());
    let stats = cache.stats();
    cache.put_json(
        "too-big",
        &RawValue::from_string(serde_json::to_string(&text.repeat(100)).unwrap()).unwrap(),
    );
    assert!(cache.get_json("key-7").is_some());
    assert!(cache.stats().bytes <= stats.max_bytes);
}

#[test]
fn unsupported_auto_vacuum_cache_is_disabled_untouched_and_full_cache_can_shrink() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("legacy-none.sqlite");
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute_batch("CREATE TABLE entries(key TEXT PRIMARY KEY,value BLOB NOT NULL,size INTEGER NOT NULL,touched INTEGER NOT NULL);CREATE INDEX cache_lru ON entries(touched);INSERT INTO entries VALUES('large',zeroblob(200000),200000,1);").unwrap();
    drop(db);
    let before = std::fs::read(&path).unwrap();
    let cache = ArtifactCache::open(&path, 0.065536).unwrap();
    assert!(
        !cache.stats().enabled,
        "unsupported auto-vacuum enabled at {} > {} bytes",
        cache.stats().bytes,
        cache.stats().max_bytes
    );
    assert!(cache.stats().error.is_some());
    assert_eq!(std::fs::read(&path).unwrap(), before);
    let path = temp.path().join("full.sqlite");
    let cache = ArtifactCache::open(&path, 2.).unwrap();
    assert!(cache.stats().enabled);
    drop(cache);
    let db = rusqlite::Connection::open(&path).unwrap();
    db.execute_batch("INSERT INTO entries VALUES('large',zeroblob(200000),200000,1);")
        .unwrap();
    drop(db);
    let cache = ArtifactCache::open(&path, 0.065536).unwrap();
    assert!(cache.stats().enabled, "{:?}", cache.stats());
    assert!(cache.stats().bytes <= cache.stats().max_bytes);
}
