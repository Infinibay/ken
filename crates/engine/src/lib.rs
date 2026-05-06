pub mod types;
pub mod storage;
pub mod embed;
pub mod rank;
pub mod ingest;
pub mod ingest_md;
pub mod ingest_html;
pub mod annotate;

#[cfg(feature = "code")]
pub mod ingest_code;

#[cfg(feature = "pdf")]
pub mod ingest_pdf;

#[cfg(feature = "git")]
pub mod ingest_git;

#[cfg(feature = "postgres")]
pub mod postgres;

#[cfg(feature = "postgres")]
pub mod ingest_fs;

#[cfg(feature = "fastembed")]
pub mod embed_fast;
