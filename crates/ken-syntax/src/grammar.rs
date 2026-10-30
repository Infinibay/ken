//! Verified grammar selection and native module lifetime ownership.
use crate::syntax::SyntaxTree;
use libloading::Library;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
use thiserror::Error;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    Bash,
    C,
    Cpp,
    CSharp,
    Css,
    Dart,
    Go,
    GraphQL,
    Html,
    Java,
    JavaScript,
    Kotlin,
    Php,
    PowerShell,
    Python,
    Ruby,
    Rust,
    Sql,
    TypeScript,
}
impl Language {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Bash => "bash",
            Self::C => "c",
            Self::Cpp => "cpp",
            Self::CSharp => "csharp",
            Self::Css => "css",
            Self::Dart => "dart",
            Self::Go => "go",
            Self::GraphQL => "graphql",
            Self::Html => "html",
            Self::Java => "java",
            Self::JavaScript => "javascript",
            Self::Kotlin => "kotlin",
            Self::Php => "php",
            Self::PowerShell => "powershell",
            Self::Python => "python",
            Self::Ruby => "ruby",
            Self::Rust => "rust",
            Self::Sql => "sql",
            Self::TypeScript => "typescript",
        }
    }
}

#[derive(Debug, Error)]
pub enum ParseError {
    #[error("invalid utf-8 in source annotation: {0}")]
    AnnotationEncoding(#[from] std::str::Utf8Error),
    #[error("invalid native grammar manifest: {0}")]
    Manifest(String),
    #[error("{language} grammar unavailable: {reason}")]
    Grammar { language: String, reason: String },
    #[error("{language} parse failed: {reason}")]
    Parse { language: String, reason: String },
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Resource {
    language: Language,
    file: String,
    bytes: u64,
    sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    format: String,
    platform: String,
    pack_version: String,
    pack_revision: String,
    libraries: Vec<Resource>,
}

// Field order matters: drop the language before unloading its native module.
pub(crate) struct Grammar {
    pub language: tree_sitter::Language,
    _library: Option<Library>,
}

pub struct GrammarCatalog {
    root: PathBuf,
    resources: BTreeMap<Language, Resource>,
    loaded: Mutex<BTreeMap<Language, Arc<Grammar>>>,
}

fn platform() -> &'static str {
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "macos-arm64"
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        "linux-aarch64"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "linux-x86_64"
    } else {
        "unsupported-platform"
    }
}
fn manifest_error(error: impl std::fmt::Display) -> ParseError {
    ParseError::Manifest(error.to_string())
}
fn grammar_error(language: Language, error: impl std::fmt::Display) -> ParseError {
    ParseError::Grammar {
        language: language.as_str().into(),
        reason: error.to_string(),
    }
}

impl GrammarCatalog {
    pub fn prepared(path: &Path) -> Result<Self, ParseError> {
        let raw = fs::read(path).map_err(manifest_error)?;
        if raw.len() > 128 * 1024 {
            return Err(manifest_error("manifest exceeds128KiB"));
        }
        let manifest: Manifest = serde_json::from_slice(&raw).map_err(manifest_error)?;
        let lock: serde_json::Value =
            serde_json::from_str(include_str!("../grammars.lock.json")).map_err(manifest_error)?;
        let pack = &lock["pack"];
        if manifest.format != "ken-native-grammars/1"
            || manifest.platform != platform()
            || pack["version"] != manifest.pack_version
            || pack["revision"] != manifest.pack_revision
        {
            return Err(manifest_error(
                "format, platform or grammar revision differs",
            ));
        }
        let pinned = pack["bundles"][platform()]["libraries"]
            .as_object()
            .ok_or_else(|| manifest_error("unsupported native grammar platform"))?;
        let mut resources = BTreeMap::new();
        let mut filenames = BTreeSet::new();
        for resource in manifest.libraries {
            let expected = pinned
                .get(resource.language.as_str())
                .ok_or_else(|| manifest_error("unknown native grammar"))?;
            if Path::new(&resource.file)
                .file_name()
                .and_then(|p| p.to_str())
                != Some(resource.file.as_str())
                || expected["file"] != resource.file
                || expected["bytes"] != resource.bytes
                || expected["sha256"] != resource.sha256
                || !filenames.insert(resource.file.clone())
                || resources.insert(resource.language, resource).is_some()
            {
                return Err(manifest_error(
                    "duplicate, unsafe or unpinned native grammar identity",
                ));
            }
        }
        if resources.len() != pinned.len() {
            return Err(manifest_error("incomplete native grammar inventory"));
        }
        let root =
            fs::canonicalize(path.parent().unwrap_or(Path::new("."))).map_err(manifest_error)?;
        Ok(Self {
            root,
            resources,
            loaded: Mutex::new(BTreeMap::new()),
        })
    }

    fn grammar(
        &self,
        language: Language,
        hint: &str,
        check: &mut dyn FnMut() -> Result<(), ParseError>,
    ) -> Result<Arc<Grammar>, ParseError> {
        let builtin = match language {
            Language::Python => Some(tree_sitter_python::LANGUAGE),
            Language::Rust => Some(tree_sitter_rust::LANGUAGE),
            Language::JavaScript => Some(tree_sitter_javascript::LANGUAGE),
            Language::Go => Some(tree_sitter_go::LANGUAGE),
            Language::Java => Some(tree_sitter_java::LANGUAGE),
            Language::TypeScript if hint.ends_with(".tsx") => {
                Some(tree_sitter_typescript::LANGUAGE_TSX)
            }
            Language::TypeScript => Some(tree_sitter_typescript::LANGUAGE_TYPESCRIPT),
            _ => None,
        };
        if let Some(builtin) = builtin {
            return Ok(Arc::new(Grammar {
                language: builtin.into(),
                _library: None,
            }));
        }
        let mut loaded = loop {
            check()?;
            match self.loaded.try_lock() {
                Ok(loaded) => break loaded,
                Err(std::sync::TryLockError::WouldBlock) => {
                    std::thread::sleep(std::time::Duration::from_millis(1))
                }
                Err(error) => return Err(grammar_error(language, error)),
            }
        };
        if let Some(grammar) = loaded.get(&language) {
            return Ok(Arc::clone(grammar));
        }
        let resource = self
            .resources
            .get(&language)
            .ok_or_else(|| grammar_error(language, "no prepared module"))?;
        let path = self.root.join(&resource.file);
        let metadata = fs::symlink_metadata(&path).map_err(|e| grammar_error(language, e))?;
        if !metadata.is_file() || metadata.len() != resource.bytes {
            return Err(grammar_error(language, "native module identity differs"));
        }
        use std::io::Read;
        let mut file = fs::File::open(&path).map_err(|e| grammar_error(language, e))?;
        let mut hash = Sha256::new();
        let mut count = 0u64;
        let mut chunk = [0u8; 8192];
        loop {
            check()?;
            let size = file
                .read(&mut chunk)
                .map_err(|e| grammar_error(language, e))?;
            if size == 0 {
                break;
            }
            count += size as u64;
            hash.update(&chunk[..size]);
        }
        check()?;
        if count != resource.bytes || format!("{:x}", hash.finalize()) != resource.sha256 {
            return Err(grammar_error(language, "native module identity differs"));
        }
        // SAFETY: bytes match a platform-specific immutable official module in
        // the compiled lock. Its C language function has tree-sitter's ABI. The
        // owned library lease outlives every tree and node that uses its pointers.
        let library = unsafe { Library::new(&path) }.map_err(|e| grammar_error(language, e))?;
        let symbol = if language == Language::CSharp {
            "tree_sitter_c_sharp".into()
        } else {
            format!("tree_sitter_{}", language.as_str())
        };
        let function =
            unsafe { library.get::<unsafe extern "C" fn() -> *const ()>(symbol.as_bytes()) }
                .map_err(|e| grammar_error(language, e))?;
        let native = unsafe { tree_sitter_language::LanguageFn::from_raw(*function) };
        let grammar = Arc::new(Grammar {
            language: tree_sitter::Language::new(native),
            _library: Some(library),
        });
        loaded.insert(language, Arc::clone(&grammar));
        Ok(grammar)
    }

    pub fn syntax(
        &self,
        language: Language,
        source: &[u8],
        hint: &str,
    ) -> Result<SyntaxTree, ParseError> {
        self.syntax_checked(language, source, hint, &mut || Ok(()))
    }
    /// Poll during a single parse, retaining the exact caller interruption error.
    pub fn syntax_checked(
        &self,
        language: Language,
        source: &[u8],
        hint: &str,
        check: &mut dyn FnMut() -> Result<(), ParseError>,
    ) -> Result<SyntaxTree, ParseError> {
        check()?;
        let grammar = self.grammar(language, hint, check)?;
        check()?;
        let mut parser = tree_sitter::Parser::new();
        parser
            .set_language(&grammar.language)
            .map_err(|e| grammar_error(language, e))?;
        let mut stopped = None;
        let tree = {
            let mut progress = |_: &tree_sitter::ParseState| match check() {
                Ok(()) => false,
                Err(error) => {
                    stopped = Some(error);
                    true
                }
            };
            parser.parse_with_options(
                &mut |offset, _| source.get(offset..).unwrap_or(&[]),
                None,
                Some(tree_sitter::ParseOptions::new().progress_callback(&mut progress)),
            )
        };
        if let Some(error) = stopped {
            return Err(error);
        }
        check()?;
        let tree = tree.ok_or_else(|| ParseError::Parse {
            language: language.as_str().into(),
            reason: "parser returned no tree".into(),
        })?;
        Ok(SyntaxTree::new(tree, grammar))
    }
}
