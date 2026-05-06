//! Tiny URL fetch + link-extraction toolkit shared by the `ingest-url` CLI
//! verb and the `/ingest_url` HTTP route. Hand-rolled (no `reqwest` /
//! `scraper`) because we already pull `ureq` for sync HTTP and the link
//! extraction surface is small enough that the regex-light scan beats
//! pulling html5ever.

use anyhow::{Context, Result};

/// Cap on response body size. Pages that blow this up are almost always
/// not docs-style content (binary blobs, video, big PDFs); rejecting them
/// keeps memory bounded for the MCP-over-stdio path.
pub const MAX_BODY_BYTES: usize = 4 * 1024 * 1024;

/// Build a sync `ureq::Agent` with the timeouts + UA we want every fetch
/// to inherit. Both the CLI and the HTTP route construct one of these per
/// crawl invocation; the agent is cheap to clone and safe to send across
/// `spawn_blocking`.
pub fn build_agent(timeout_secs: u64) -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout(std::time::Duration::from_secs(timeout_secs))
        .user_agent("ken/0.1 (ingest-url)")
        .build()
}

/// Fetch a URL with a hard 4 MiB body cap. Returns the lower-cased mime
/// (with parameters stripped) and the raw bytes. Any HTTP error or oversized
/// body becomes a returned error — caller decides whether to skip or abort.
pub fn fetch_url(agent: &ureq::Agent, url: &str) -> Result<(String, Vec<u8>)> {
    let resp = agent.get(url).call().map_err(|e| anyhow::anyhow!("{e}"))?;
    let mime = resp
        .header("content-type")
        .map(|s| s.split(';').next().unwrap_or(s).trim().to_lowercase())
        .unwrap_or_else(|| "application/octet-stream".into());
    let mut reader = resp.into_reader().take(MAX_BODY_BYTES as u64 + 1);
    let mut bytes = Vec::with_capacity(64 * 1024);
    use std::io::Read;
    reader.read_to_end(&mut bytes).context("read response body")?;
    if bytes.len() > MAX_BODY_BYTES {
        anyhow::bail!("body exceeds {} MiB cap", MAX_BODY_BYTES / (1024 * 1024));
    }
    Ok((mime, bytes))
}

/// Canonicalize a URL for the visited-set: drop fragment, drop trailing
/// slash, lowercase the host. Two links to the same page with different
/// fragments shouldn't both fetch.
pub fn canonical_url(u: &url::Url) -> String {
    let mut s = format!(
        "{}://{}{}",
        u.scheme(),
        u.host_str().unwrap_or("").to_ascii_lowercase(),
        u.path().trim_end_matches('/')
    );
    if let Some(q) = u.query() {
        s.push('?');
        s.push_str(q);
    }
    s
}

/// Extract `href="..."` and `href='...'` from anchor tags. Resolves relative
/// links against `base`. Hand-rolled scan — good enough for blog posts and
/// docs sites; pathological HTML produces some noise but the visited-set and
/// max-pages cap absorb it. Lowercase scan for the tag opener; the actual
/// href value is read from the original-case bytes so paths aren't mangled.
pub fn extract_links(base: &url::Url, html: &str) -> Vec<url::Url> {
    let mut out = Vec::new();
    let lower = html.to_ascii_lowercase();
    let mut cursor = 0usize;
    while let Some(rel) = lower[cursor..].find("<a ") {
        let tag_start = cursor + rel;
        if let Some(href) = extract_href_from_tag(html, tag_start)
            && let Ok(joined) = base.join(&href)
            && acceptable_link(&joined)
        {
            out.push(joined);
        }
        cursor = tag_start + 3;
    }
    out
}

fn extract_href_from_tag(html: &str, start_byte: usize) -> Option<String> {
    let after = &html[start_byte..];
    let close = after.find('>')?;
    let tag = &after[..close];
    let lower = tag.to_ascii_lowercase();
    let href_idx = lower.find("href")?;
    let after_href = &tag[href_idx + 4..];
    let trimmed = after_href.trim_start();
    let trimmed = trimmed.strip_prefix('=')?.trim_start();
    let (delim, body) = match trimmed.chars().next()? {
        '"' => ('"', &trimmed[1..]),
        '\'' => ('\'', &trimmed[1..]),
        _ => return None,
    };
    let end = body.find(delim)?;
    Some(body[..end].to_string())
}

pub fn acceptable_link(u: &url::Url) -> bool {
    matches!(u.scheme(), "http" | "https")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_drops_fragment_and_trailing_slash() {
        let u = url::Url::parse("https://Example.com/foo/#bar").unwrap();
        assert_eq!(canonical_url(&u), "https://example.com/foo");
    }

    #[test]
    fn extract_links_handles_relative_and_absolute() {
        let base = url::Url::parse("https://x.test/docs/").unwrap();
        let html = r#"<a href="page.html">a</a> <a href='/abs'>b</a> <a href="https://other.test/y">c</a>"#;
        let links = extract_links(&base, html);
        let urls: Vec<String> = links.iter().map(|u| u.to_string()).collect();
        assert!(urls.iter().any(|u| u == "https://x.test/docs/page.html"));
        assert!(urls.iter().any(|u| u == "https://x.test/abs"));
        assert!(urls.iter().any(|u| u == "https://other.test/y"));
    }

    #[test]
    fn acceptable_only_http_https() {
        assert!(acceptable_link(&url::Url::parse("https://x.test").unwrap()));
        assert!(acceptable_link(&url::Url::parse("http://x.test").unwrap()));
        assert!(!acceptable_link(&url::Url::parse("javascript:void(0)").unwrap()));
        assert!(!acceptable_link(&url::Url::parse("mailto:a@b.test").unwrap()));
    }
}
