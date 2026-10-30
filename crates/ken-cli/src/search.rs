//! CLI options select the shared public application and its output representation.
use crate::{
    args::{PieceKind, Purpose, ResponseFormat, SearchArgs},
    status::CommandOutput,
};
use ken_application::{
    knowledge::EmbeddingResources,
    search_compat::{CompatibilityModels, SearchCompatibility},
};
use ken_core::project::DiscoveryContext;
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, ModelFactory};
use ken_retrieval::query::{SearchOptions, SearchRequest};
use ken_retrieval::{
    Result as RetrievalResult, RetrievalError,
    project_embeddings::TransformerOverrides,
    query_encoder::QueryEncoder,
    ranking::{JointModelJudge, RelevanceJudge},
};
use ken_search::public::{ApplicationError, SearchApplication, resolve_index};
use ken_text::PythonText;
use rusqlite::Connection;
use std::{cell::RefCell, collections::BTreeMap, path::PathBuf, rc::Rc, sync::Arc};

pub(crate) struct CompatibilityResources {
    installation: PathBuf,
    environment: BTreeMap<String, String>,
    factory: RefCell<Option<Arc<ModelFactory>>>,
    focused: RefCell<Option<Rc<EmbeddingResources>>>,
    legacy: RefCell<Option<LegacyRuntimeIdentity>>,
}
impl CompatibilityResources {
    pub(crate) fn new(installation: PathBuf) -> Rc<Self> {
        Rc::new(Self {
            installation,
            environment: crate::runtime::environment(),
            factory: RefCell::new(None),
            focused: RefCell::new(None),
            legacy: RefCell::new(None),
        })
    }
    pub(crate) fn owner(
        self: &Rc<Self>,
    ) -> Result<SearchCompatibility, Box<dyn std::error::Error>> {
        let legacy = self.legacy.borrow().clone();
        let legacy = match legacy {
            Some(legacy) => legacy,
            None => {
                let legacy =
                    ken_search::SearchInstallation::declared_legacy_runtime(&self.installation)?;
                self.legacy.replace(Some(legacy.clone()));
                legacy
            }
        };
        Ok(SearchCompatibility::new(self.clone(), legacy))
    }
    fn factory(&self) -> RetrievalResult<Arc<ModelFactory>> {
        if let Some(factory) = self.factory.borrow().as_ref() {
            return Ok(factory.clone());
        }
        let factory = crate::runtime::model_factory(&self.installation, &self.environment)
            .map_err(|error| RetrievalError::Invalid(error.to_string()))?;
        self.factory.replace(Some(factory.clone()));
        Ok(factory)
    }
    fn focused(&self) -> RetrievalResult<Rc<EmbeddingResources>> {
        if let Some(resources) = self.focused.borrow().as_ref() {
            return Ok(resources.clone());
        }
        let resources = Rc::new(EmbeddingResources::new(
            self.factory()?,
            crate::runtime::user_config(&self.environment),
            self.environment.get("KEN_EMBED_MODEL").cloned(),
            TransformerOverrides {
                sequence_length: self.environment.get("KEN_EMBED_MAX_SEQ").cloned(),
                batch_size: self.environment.get("KEN_EMBED_BATCH").cloned(),
            },
        ));
        self.focused.replace(Some(resources.clone()));
        Ok(resources)
    }
}
impl CompatibilityModels for CompatibilityResources {
    fn legacy_query(&self, conn: &Connection, query: &PythonText) -> RetrievalResult<Vec<f32>> {
        self.focused()?.project(conn)?.embed_query(query)
    }
    fn profile_query(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
        query: &PythonText,
    ) -> RetrievalResult<Vec<f32>> {
        ken_retrieval::query_encoder::ManagedQueryEncoder(self.factory()?.encoder(spec, legacy)?)
            .embed_query(query)
    }
    fn joint_judge(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> RetrievalResult<Rc<dyn RelevanceJudge>> {
        Ok(Rc::new(JointModelJudge(
            self.factory()?.judge(spec, legacy)?,
        )))
    }
}
/// A selected compatibility request does not open grammars or BestSearch roles.
pub(crate) fn compatibility(
    installation: PathBuf,
) -> Result<SearchCompatibility, Box<dyn std::error::Error>> {
    CompatibilityResources::new(installation).owner()
}

fn failure(message: &str) -> CommandOutput {
    CommandOutput {
        code: 1,
        stdout: String::new(),
        stderr: format!("error: {message}\n"),
    }
}
pub fn run(
    args: SearchArgs,
    target: &str,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    let paths = match resolve_index(&args.path, context) {
        Ok(paths) => paths,
        Err(ApplicationError::MissingProject(root)) => {
            return Ok(failure(&format!("no .ken project at {}", root.display())));
        }
        Err(error) => return Err(error.into()),
    };
    if args.response_format == ResponseFormat::Compact && args.json {
        return Ok(failure(
            "compact is text; use --response-format evidence --json for structured output",
        ));
    }
    if !matches!(
        args.response_format,
        ResponseFormat::Auto | ResponseFormat::Compact
    ) {
        if args.piece_kind != PieceKind::Auto {
            return Ok(failure(
                "--piece-kind requires the default or compact response mode",
            ));
        }
        if args.response_format == ResponseFormat::Legacy && args.purpose != Purpose::Auto {
            return Ok(failure(
                "--purpose requires --response-format evidence or compact",
            ));
        }
        let db = ken_store::ProjectDatabase::open(&paths.db())?;
        if args.response_format == ResponseFormat::Legacy {
            let response = compatibility(installation)?.legacy(
                db.connection(),
                Some(paths.root()),
                &args.query.join(" ").into(),
                if target == "file" { "files" } else { "symbols" },
                args.limit,
            )?;
            let stdout = if args.json {
                serde_json::to_string_pretty(&response)?
            } else {
                response.render()
            };
            return Ok(CommandOutput {
                code: 0,
                stdout: stdout + "\n",
                stderr: String::new(),
            });
        }
        let request: SearchRequest = SearchOptions {
            query: args.query.join(" ").into(),
            target: target.into(),
            purpose: args.purpose.as_str().into(),
            limit: args.limit,
            max_chars: args.max_chars,
            explain: false,
            piece_kind: None,
        }
        .try_into()?;
        let response = match SearchCompatibility::evidence_requirement(db.connection())? {
            Some(required) => required,
            None => compatibility(installation)?.evidence(db.connection(), &paths, &request)?,
        };
        let stdout = if args.json {
            serde_json::to_string(&response)?
        } else {
            response.render(false)
        };
        return Ok(CommandOutput {
            code: u8::from(!response.is_success()),
            stdout: stdout + "\n",
            stderr: String::new(),
        });
    }
    let request: SearchRequest = SearchOptions {
        query: args.query.join(" ").into(),
        target: target.into(),
        purpose: args.purpose.as_str().into(),
        limit: args.limit,
        max_chars: args.max_chars,
        piece_kind: args.piece_kind.as_str().map(str::to_owned),
        explain: false,
    }
    .try_into()?;
    let response = SearchApplication::new(installation).find(&paths, &request)?;
    let stdout = if args.json {
        serde_json::to_string(&response)?
    } else {
        response.render(false)
    };
    Ok(CommandOutput {
        code: u8::from(!response.is_success()),
        stdout: stdout + "\n",
        stderr: String::new(),
    })
}
