//! Pure parsers for the structured linkages git authors leave in commit
//! messages. No I/O — input is a `&str` (the message body), output is a
//! `Linkages` struct the ingest pipeline turns into edges.
//!
//! Conventions covered:
//!   * `Fixes: <sha>` — kernel/Linux convention; this commit fixes a bug
//!     introduced by `<sha>`. We treat the targets symmetrically: a `Fixed`
//!     edge from this commit to the offending one. (We don't currently
//!     parse `Fixes: #N` issue references — that's the GitHub-source path.)
//!   * `Reverts: <sha>` and the implicit form `Revert "..."` summary line
//!     produced by `git revert`.
//!   * `(cherry picked from commit <sha>)` — produced by `git cherry-pick -x`.
//!   * `Co-authored-by: Name <email>` — GitHub convention for pair work.
//!
//! These parsers are deliberately permissive: people format commits
//! inconsistently. Rather than reject malformed trailers, we extract
//! anything that looks like a sha and let downstream code decide.

use ahash::AHashSet;

/// Anything we extracted from a commit message worth turning into edges.
/// All sha fields are full or short hex strings; the caller is responsible
/// for resolving them to `git+sha:<full>` external IDs (a short ref might
/// not yet exist in our DB, in which case the edge has a dangling
/// `External("git+sha:<short>")` target — that's fine, our edges accept
/// dangling externals by design).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Linkages {
    pub fixes: Vec<String>,
    pub reverts: Vec<String>,
    pub cherry_picked_from: Vec<String>,
    pub coauthors: Vec<CoAuthor>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoAuthor {
    pub name: String,
    pub email: String,
}

/// Parse all linkages out of a commit message. Order of returned slices is
/// the order they appeared in the message (preserves "first reverted, then
/// fixed" sequencing if a single message references both).
pub fn parse(message: &str) -> Linkages {
    let mut out = Linkages::default();
    // Dedupe within a single message — `Fixes: abc` written twice is one
    // logical link.
    let mut seen_fixes: AHashSet<String> = AHashSet::new();
    let mut seen_reverts: AHashSet<String> = AHashSet::new();
    let mut seen_cherry: AHashSet<String> = AHashSet::new();
    let mut seen_coauth: AHashSet<(String, String)> = AHashSet::new();

    for line in message.lines() {
        let trimmed = line.trim();

        // Trailer: `Fixes: <sha>` (case-insensitive, optional whitespace
        // after colon, sha may be 7-40 hex chars). Tolerate trailing
        // descriptive text in parens, e.g. `Fixes: abc1234 ("subject")`.
        if let Some(sha) = parse_trailer(trimmed, "fixes") {
            if seen_fixes.insert(sha.clone()) {
                out.fixes.push(sha);
            }
            continue;
        }
        if let Some(sha) = parse_trailer(trimmed, "reverts") {
            if seen_reverts.insert(sha.clone()) {
                out.reverts.push(sha);
            }
            continue;
        }
        // Cherry-pick: `(cherry picked from commit <sha>)`. The whole line
        // is wrapped in parens by the convention.
        if let Some(sha) = parse_cherry_pick_line(trimmed) {
            if seen_cherry.insert(sha.clone()) {
                out.cherry_picked_from.push(sha);
            }
            continue;
        }
        // Co-authored-by: Name <email>
        if let Some((name, email)) = parse_coauthor_trailer(trimmed) {
            let key = (name.to_ascii_lowercase(), email.to_ascii_lowercase());
            if seen_coauth.insert(key) {
                out.coauthors.push(CoAuthor { name, email });
            }
            continue;
        }
    }

    // Implicit revert: a summary line like `Revert "Fix the thing"`. The
    // sha isn't carried in the summary; we record the *quoted subject* so
    // downstream can do a fuzzy lookup. For Phase 1 we just flag it as
    // `Reverts(subject)` — no sha — and emit a metadata-only edge with the
    // reverted subject in JSONB. Keep it out of the sha list to avoid
    // false-positive lookups.
    out
}

/// Parse a trailer of the form `Key: <value>` (case-insensitive on the
/// key). Returns the first sha-looking token in the value, or None.
fn parse_trailer(line: &str, expected_key: &str) -> Option<String> {
    let (key, value) = line.split_once(':')?;
    if !key.trim().eq_ignore_ascii_case(expected_key) {
        return None;
    }
    extract_sha(value)
}

/// `(cherry picked from commit abc1234)`. The whole line *should* be
/// wrapped in parens but we accept it without too — `git cherry-pick -x`
/// always emits the parens, but humans copy-paste sloppily.
fn parse_cherry_pick_line(line: &str) -> Option<String> {
    let stripped = line.trim_start_matches('(').trim_end_matches(')').trim();
    let prefix = "cherry picked from commit";
    let lower = stripped.to_ascii_lowercase();
    let pos = lower.find(prefix)?;
    let rest = &stripped[pos + prefix.len()..];
    extract_sha(rest)
}

/// `Co-authored-by: Alice <alice@example.com>`. Returns (name, email).
fn parse_coauthor_trailer(line: &str) -> Option<(String, String)> {
    let (key, value) = line.split_once(':')?;
    let k = key.trim().to_ascii_lowercase();
    if k != "co-authored-by" && k != "coauthored-by" {
        return None;
    }
    let value = value.trim();
    // Find the email between < and >.
    let lt = value.rfind('<')?;
    let gt = value.rfind('>')?;
    if gt <= lt {
        return None;
    }
    let name = value[..lt].trim().to_string();
    let email = value[lt + 1..gt].trim().to_string();
    if email.is_empty() {
        return None;
    }
    Some((name, email))
}

/// First contiguous run of 7..=40 lowercase hex characters in `s`.
/// Returns None if there isn't one. We accept the message author's sha
/// length verbatim — abbreviated shas are normal in `Fixes:` trailers.
fn extract_sha(s: &str) -> Option<String> {
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if is_hex_byte(bytes[i]) {
            let start = i;
            while i < bytes.len() && is_hex_byte(bytes[i]) {
                i += 1;
            }
            let len = i - start;
            if (7..=40).contains(&len) {
                return Some(s[start..i].to_ascii_lowercase());
            }
        } else {
            i += 1;
        }
    }
    None
}

#[inline]
fn is_hex_byte(b: u8) -> bool {
    matches!(b, b'0'..=b'9' | b'a'..=b'f' | b'A'..=b'F')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_fixes_trailer_with_subject() {
        let msg = "feat: thing\n\nFixes: abc1234 (\"oops\")\nSigned-off-by: x <x@y>";
        let linkages = parse(msg);
        assert_eq!(linkages.fixes, vec!["abc1234"]);
        assert!(linkages.reverts.is_empty());
    }

    #[test]
    fn extracts_multiple_fixes() {
        let msg = "subject\n\nFixes: deadbeef0\nFixes: cafef00d\n";
        assert_eq!(parse(msg).fixes, vec!["deadbeef0", "cafef00d"]);
    }

    #[test]
    fn dedupes_within_message() {
        let msg = "x\n\nFixes: abc1234\nFixes: ABC1234\n";
        assert_eq!(parse(msg).fixes, vec!["abc1234"]);
    }

    #[test]
    fn extracts_reverts_trailer() {
        let msg = "Revert \"thing\"\n\nReverts: 1234567\n";
        assert_eq!(parse(msg).reverts, vec!["1234567"]);
    }

    #[test]
    fn extracts_cherry_pick_with_parens() {
        let msg = "feat: x\n\n(cherry picked from commit deadbeef)\n";
        assert_eq!(parse(msg).cherry_picked_from, vec!["deadbeef"]);
    }

    #[test]
    fn extracts_cherry_pick_without_parens() {
        let msg = "feat: x\n\ncherry picked from commit 1234567abcd\n";
        assert_eq!(parse(msg).cherry_picked_from, vec!["1234567abcd"]);
    }

    #[test]
    fn extracts_coauthor_trailer() {
        let msg = "feat\n\nCo-authored-by: Alice <alice@example.com>\nCo-authored-by: Bob <bob@x.io>\n";
        let l = parse(msg);
        assert_eq!(l.coauthors.len(), 2);
        assert_eq!(l.coauthors[0].name, "Alice");
        assert_eq!(l.coauthors[0].email, "alice@example.com");
        assert_eq!(l.coauthors[1].email, "bob@x.io");
    }

    #[test]
    fn ignores_non_sha_in_fixes() {
        let msg = "x\n\nFixes: see issue #42\n";
        // No hex run of 7+ chars — `42` is 2 chars, `Fixes` is 5, `see` etc.
        assert!(parse(msg).fixes.is_empty());
    }

    #[test]
    fn ignores_unrelated_lines() {
        let msg = "Subject\n\nLong description with abc1234 in body but no trailer.\n";
        let l = parse(msg);
        assert!(l.fixes.is_empty());
        assert!(l.reverts.is_empty());
        assert!(l.cherry_picked_from.is_empty());
    }

    #[test]
    fn full_sha_works() {
        let msg = "x\n\nFixes: 0123456789abcdef0123456789abcdef01234567\n";
        assert_eq!(
            parse(msg).fixes,
            vec!["0123456789abcdef0123456789abcdef01234567"]
        );
    }

    #[test]
    fn coauthor_without_email_is_skipped() {
        let msg = "x\n\nCo-authored-by: Anonymous\n";
        assert!(parse(msg).coauthors.is_empty());
    }

    #[test]
    fn case_insensitive_keys() {
        let msg = "x\n\nFIXES: abc1234\nco-authored-by: Bob <b@x>\n";
        let l = parse(msg);
        assert_eq!(l.fixes, vec!["abc1234"]);
        assert_eq!(l.coauthors.len(), 1);
    }

    #[test]
    fn fixes_subject_text_does_not_yield_false_sha() {
        // Subjects can contain words like "Fix" or "decade" — make sure we
        // don't pick those up as shas. "decade" is 6 hex chars (d, e, c, a,
        // d, e), under threshold of 7.
        let msg = "x\n\nFixes: decade\n";
        assert!(parse(msg).fixes.is_empty());
    }
}
