//! CLI presentation delegates explicit maintenance and source/model decisions.
use crate::status::CommandOutput;
use clap::{Subcommand, ValueEnum};
use ken_core::project::{DiscoveryContext, ProjectPaths, locate_project};
use ken_maintenance::{
    ConfigEnvironment, MaintenanceApplication, ModelSelection, UserConfig, VectorAction,
};
use ken_models::{ModelCatalog, ModelFactory};
use ken_retrieval::{
    DocumentEncoder,
    project_embeddings::{ProjectEmbeddings, TransformerOverrides},
};
use ken_search::SearchInstallation;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum VectorOperation {
    Status,
    Verify,
    Migrate,
    Compact,
}
#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum BenchEngine {
    Context,
    Retrieval,
}
#[derive(Debug, Subcommand)]
pub enum RetrievalCommand {
    /// Prepare or update source passages and declared local model views
    Index {
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        profile: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Prepare the complete native CPU search configuration
    Prepare {
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
}
#[derive(Debug, Subcommand)]
pub enum MaintenanceCommand {
    /// List registered embedding models without loading their assets
    Models {
        #[arg(long)]
        json: bool,
    },
    /// Show or change the embedding model for new projects
    DefaultModel {
        model: Option<String>,
        #[arg(long)]
        clear: bool,
    },
    /// Inspect, verify, migrate or compact mapped vector spaces
    Vectors {
        #[arg(value_enum, default_value = "status")]
        action: VectorOperation,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
    /// Explicitly reencode every stored embedding or check its probe
    Reembed {
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        model: Option<String>,
        #[arg(long)]
        check: bool,
        #[arg(long)]
        json: bool,
    },
    /// Prepare source retrieval profiles and the complete search configuration
    Retrieval {
        #[command(subcommand)]
        command: RetrievalCommand,
    },
    /// Evaluate context rankings or score frozen retrieval responses
    Bench {
        dataset: PathBuf,
        #[arg(long, value_enum, default_value = "context")]
        engine: BenchEngine,
        #[arg(long)]
        responses: Option<PathBuf>,
        #[arg(long)]
        roots: Option<PathBuf>,
        #[arg(long)]
        gate: Option<PathBuf>,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long,default_value_t=8,value_parser=positive)]
        top: usize,
        #[arg(long, default_value_t = 0, allow_hyphen_values = true)]
        max_chars: i64,
        #[arg(long)]
        fail_under_case_recall: Option<f64>,
        #[arg(long)]
        fail_under_expected_file_recall: Option<f64>,
        #[arg(long)]
        explain_misses: bool,
        #[arg(long)]
        json: bool,
    },
}
fn positive(raw: &str) -> std::result::Result<usize, String> {
    raw.parse::<usize>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| "must be a positive integer".into())
}
fn output(code: u8, stdout: String, stderr: String) -> CommandOutput {
    CommandOutput {
        code,
        stdout,
        stderr,
    }
}
fn failure(code: u8, message: impl std::fmt::Display) -> CommandOutput {
    output(code, String::new(), format!("error: {message}\n"))
}
fn json_output(value: &impl serde::Serialize, code: u8) -> Result<CommandOutput> {
    Ok(output(
        code,
        serde_json::to_string_pretty(value)? + "\n",
        String::new(),
    ))
}
fn input_path(path: &Path, context: &DiscoveryContext) -> PathBuf {
    if path.is_absolute() {
        path.into()
    } else {
        context.cwd.join(path)
    }
}
fn project(path: &Path, context: &DiscoveryContext, discover: bool) -> Result<ProjectPaths> {
    if discover && let Some(paths) = locate_project(path, context)? {
        return Ok(paths);
    }
    Ok(ProjectPaths::at(path, context)?)
}
struct HostInputs {
    environment: BTreeMap<String, String>,
    config: UserConfig,
}
impl HostInputs {
    fn capture(context: &DiscoveryContext) -> Self {
        let raw = std::env::vars_os().collect::<BTreeMap<_, _>>();
        let environment = raw
            .iter()
            .filter_map(|(key, value)| Some((key.to_str()?.to_owned(), value.to_str()?.to_owned())))
            .collect();
        let path = |name: &str| raw.get(std::ffi::OsStr::new(name)).map(PathBuf::from);
        let config = UserConfig::new(&ConfigEnvironment {
            config_dir: path("KEN_CONFIG_DIR"),
            xdg_config_home: path("XDG_CONFIG_HOME"),
            home: context
                .home
                .clone()
                .or_else(|| path("HOME"))
                .unwrap_or_default(),
        });
        Self {
            environment,
            config,
        }
    }
    fn factory(&self, installation: &Path) -> Result<Arc<ModelFactory>> {
        let (fastembed, transformer) = ken_daemon::native::device_requests(&self.environment);
        Ok(SearchInstallation::open_model_factory_with_devices(
            installation,
            fastembed,
            transformer,
        )?)
    }
    fn encoder(
        &self,
        installation: &Path,
        connection: &rusqlite::Connection,
        forced: Option<&str>,
    ) -> Result<ProjectEmbeddings> {
        let model = ModelSelection::resolve(
            connection,
            &self.config,
            self.environment.get("KEN_EMBED_MODEL").map(String::as_str),
            forced,
        )?
        .model;
        Ok(ProjectEmbeddings::new(
            self.factory(installation)?,
            model,
            TransformerOverrides {
                sequence_length: self.environment.get("KEN_EMBED_MAX_SEQ").cloned(),
                batch_size: self.environment.get("KEN_EMBED_BATCH").cloned(),
            },
        ))
    }
}
fn vectors_text(report: &Value) -> String {
    let mut lines = Vec::new();
    if let Some(spaces) = report["spaces"].as_object() {
        for (space, info) in spaces {
            if let Some(error) = info["error"].as_str() {
                lines.push(format!("{space:<20} {error}"));
                continue;
            }
            let bytes = info["bytes"].as_u64().unwrap_or(0) as f64;
            let mut line = format!("{space:<20} {:>9.1} MB", bytes / 1e6);
            if info.get("referenced").is_some() {
                line.push_str(&format!(
                    "  referenced={} free={} leaked={} out_of_range={}",
                    info["referenced"], info["free"], info["leaked"], info["out_of_range"]
                ));
            }
            if let Some(pending) = info["inline_pending"].as_u64().filter(|count| *count > 0) {
                line.push_str(&format!(
                    "  [{pending} still inline — run `ken vectors migrate`]"
                ));
            }
            lines.push(line);
        }
    } else if let Some(moved) = report["moved"].as_object() {
        for (space, count) in moved {
            lines.push(format!("  {space}: {count}"));
        }
        if let Some(error) = report["vacuum_error"].as_str() {
            lines.push(format!(
                "[vectors] VACUUM skipped ({error}); vectors moved fine"
            ));
        } else if let Some(before) = report["db_bytes_before"]
            .as_u64()
            .filter(|before| *before > 0)
        {
            lines.push(format!(
                "[vectors] ken.db {:.1} MB -> {:.1} MB",
                before as f64 / 1e6,
                report["db_bytes_after"].as_u64().unwrap_or(before) as f64 / 1e6
            ));
        }
    } else if let Some(compacted) = report["compacted"].as_object() {
        for (space, count) in compacted {
            lines.push(format!(
                "  {space}: {} -> {} slots",
                count["before"], count["after"]
            ));
        }
    }
    if lines.is_empty() {
        String::new()
    } else {
        lines.join("\n") + "\n"
    }
}
fn models_text(report: &Value) -> String {
    let mut text = String::from(
        "registered embedding models (explicit native asset identities):\n\n   dim     MB  model\n",
    );
    if let Some(rows) = report["models"].as_array() {
        for row in rows {
            let dim = row["dim"]
                .as_u64()
                .map(|dim| dim.to_string())
                .unwrap_or_else(|| "?".into());
            let default = if row["model"] == report["default"] {
                "   ← default"
            } else {
                ""
            };
            text.push_str(&format!(
                "  {dim:>4} {:>6}  {}{default}\n",
                row["mb"],
                row["model"].as_str().unwrap_or("")
            ));
        }
    }
    text.push_str("\nSet the default for NEW projects:  ken default-model <model>\nSwitch THIS project:               ken reembed --model <model>\n");
    text
}
fn benchmark_text(report: &ken_maintenance::BenchReport) -> String {
    let mut text = format!(
        "cases={} top={} case_recall={:.2}% expected_file_recall={:.2}% mrr={:.4} ndcg={:.4} visible_file_recall={:.2}% avg_context≈{} tokens avg_embed={:.2}ms avg_rank={:.2}ms avg_render={:.2}ms avg_e2e={:.2}ms\n",
        report.cases,
        report.top,
        report.case_recall * 100.,
        report.expected_file_recall * 100.,
        report.mrr,
        report.ndcg,
        report.visible_expected_file_recall * 100.,
        report.avg_context_est_tokens,
        report.avg_timings_ms["embed"],
        report.avg_timings_ms["rank"],
        report.avg_timings_ms["render"],
        report.avg_timings_ms["e2e"]
    );
    for row in &report.results {
        text.push_str(&format!(
            "{}. {}: {} expected={:?} hits={:?} rr={:.4} ndcg={:.4} e2e={:.2}ms\n",
            row.case,
            if row.hit { "hit" } else { "miss" },
            row.prompt
                .to_utf8()
                .unwrap_or_else(|| "<non-scalar prompt>".into()),
            row.expected_files,
            row.hits,
            row.reciprocal_rank,
            row.ndcg,
            row.timings_ms.get("e2e").copied().unwrap_or(0.)
        ));
        if let Some(misses) = row.misses.as_ref().filter(|misses| !misses.is_empty()) {
            text.push_str(&format!("   misses={misses:?}\n"));
            for row in row.ranked_details.iter().take(3) {
                text.push_str(&format!(
                    "   top: {} score={} reason={}\n",
                    row.path.to_utf8().unwrap_or_default(),
                    row.score,
                    row.reason.to_utf8().unwrap_or_default()
                ));
            }
        }
    }
    text
}
struct LazyContext<'a> {
    connection: &'a rusqlite::Connection,
    root: PathBuf,
    installation: PathBuf,
    host: HostInputs,
    encoder: Option<ProjectEmbeddings>,
    numerics: ken_context::NativeNumerics,
}
impl ken_maintenance::BenchRunner for LazyContext<'_> {
    fn evaluate(
        &mut self,
        prompt: &ken_text::PythonText,
        top: usize,
        max_chars: Option<i64>,
    ) -> ken_maintenance::Result<ken_maintenance::BenchObservation> {
        if self.encoder.is_none() {
            self.encoder = Some(
                self.host
                    .encoder(&self.installation, self.connection, None)
                    .map_err(|error| ken_maintenance::Error::Invalid(error.to_string()))?,
            );
        }
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        let clock = ken_context::Clock {
            now_ms: time.as_millis().try_into().unwrap_or(i64::MAX),
            now_ns: time.as_nanos().try_into().unwrap_or(i64::MAX),
        };
        let mut runner = ken_maintenance::ContextBenchRunner::new(
            self.connection,
            &self.root,
            self.encoder.as_ref().expect("selected encoder"),
            &mut self.numerics,
            ken_context::Policy::capture(&self.host.environment)?,
            clock,
        );
        ken_maintenance::BenchRunner::evaluate(&mut runner, prompt, top, max_chars)
    }
}
pub fn run(
    command: MaintenanceCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    Ok(match execute(command, installation, context) {
        Ok(output) => output,
        Err(error) => failure(1, error),
    })
}
fn execute(
    command: MaintenanceCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput> {
    let host = HostInputs::capture(context);
    match command {
        MaintenanceCommand::Models { json: as_json } => {
            let catalog = match std::fs::metadata(&installation) {
                Ok(_) => SearchInstallation::model_catalog(&installation)?,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    ModelCatalog::built_in()?
                }
                Err(error) => return Err(error.into()),
            };
            let report = ken_maintenance::models(&host.config, &catalog)?;
            if as_json {
                json_output(&report, 0)
            } else {
                Ok(output(0, models_text(&report), String::new()))
            }
        }
        MaintenanceCommand::DefaultModel { model, clear } => {
            let text = if clear {
                let path = host.config.set_default_model(None)?;
                format!(
                    "cleared; new projects will use ken's built-in default:\n  {}\n(config: {})\n",
                    host.config.recommended_model()?,
                    path.display()
                )
            } else if let Some(model) = model.filter(|model| !model.is_empty()) {
                let path = host.config.set_default_model(Some(&model))?;
                format!(
                    "default model for new projects set to:\n  {model}\n(config: {})\nexisting projects are unaffected — switch one with: ken reembed --model <name>\n",
                    path.display()
                )
            } else {
                let source = if host.config.default_model()?.is_some() {
                    format!("your config ({})", host.config.path().display())
                } else {
                    "ken built-in default (no override set)\n  set one with:  ken default-model <model>".into()
                };
                format!(
                    "default model for new projects: {}\n  source: {source}\n",
                    host.config.recommended_model()?
                )
            };
            Ok(output(0, text, String::new()))
        }
        MaintenanceCommand::Vectors {
            action,
            path,
            json: as_json,
        } => {
            let paths = project(&path, context, false)?;
            let mut app = MaintenanceApplication::open(paths.root())?;
            let encoder = host.encoder(&installation, app.database().connection(), None)?;
            let dim = encoder.dim()?;
            let action = match action {
                VectorOperation::Status => VectorAction::Status,
                VectorOperation::Verify => VectorAction::Verify,
                VectorOperation::Migrate => VectorAction::Migrate,
                VectorOperation::Compact => VectorAction::Compact,
            };
            let report = app.vectors(action, dim, Some(encoder.model()), &mut |_| {})?;
            if as_json {
                json_output(&report, 0)
            } else {
                Ok(output(0, vectors_text(&report), String::new()))
            }
        }
        MaintenanceCommand::Reembed {
            path,
            model,
            check,
            json: as_json,
        } => {
            let paths = project(&path, context, true)?;
            let mut app = MaintenanceApplication::open(paths.root())?;
            let encoder =
                host.encoder(&installation, app.database().connection(), model.as_deref())?;
            if check {
                let report = app.validate_embeddings(encoder.model(), &encoder)?;
                let code = u8::from(!report.ok);
                if as_json {
                    return json_output(&report, code);
                }
                return Ok(if report.ok {
                    output(
                        0,
                        format!(
                            "ok: embeddings match live model '{}' (dim={}, probe cosine={})\n",
                            report.live_model,
                            report
                                .live_dim
                                .map(|dim| dim.to_string())
                                .unwrap_or_else(|| "None".into()),
                            report
                                .probe_cosine
                                .map(|cosine| cosine.to_string())
                                .unwrap_or_else(|| "None".into())
                        ),
                        String::new(),
                    )
                } else {
                    output(
                        code,
                        String::new(),
                        format!(
                            "stale: {}\n",
                            report
                                .reason
                                .unwrap_or_else(|| "unknown embedding mismatch".into())
                        ),
                    )
                });
            }
            let previous = app.stored_embedding_info()?;
            let report = app.reembed(
                encoder.model(),
                &encoder,
                &encoder,
                &Default::default(),
                &mut |_| {},
            )?;
            if as_json {
                let mut value = serde_json::to_value(&report)?;
                value["ok"] = json!(true);
                value["previous_model"] = json!(previous.model);
                json_output(&value, 0)
            } else {
                let total = report.files
                    + report.symbols
                    + report.intent
                    + report.prompts
                    + report.findings;
                let mut text = format!(
                    "previous: model={} dim={}\nmodel: {}\nsymbols: {}\nfiles: {}\nintent: {}\nprompts: {}\nfindings: {}\nre-encoded {total} embeddings with {} (dim={})\n",
                    previous.model.as_deref().unwrap_or("unknown"),
                    previous
                        .dim
                        .map(|dim| dim.to_string())
                        .unwrap_or_else(|| "unknown".into()),
                    report.model,
                    report.symbols,
                    report.files,
                    report.intent,
                    report.prompts,
                    report.findings,
                    report.model,
                    report
                        .dim
                        .map(|dim| dim.to_string())
                        .unwrap_or_else(|| "None".into())
                );
                if let (Some(previous), Some(current)) = (previous.dim, report.dim)
                    && previous > 0
                    && previous as usize != current
                {
                    text.push_str(&format!(
                        "note: dimension changed {previous} -> {current}\n"
                    ));
                }
                Ok(output(0, text, String::new()))
            }
        }
        MaintenanceCommand::Retrieval { command } => match command {
            RetrievalCommand::Index {
                path,
                profile,
                json: as_json,
            } => {
                let path = input_path(&path, context);
                let profile = profile
                    .map(|path| {
                        let raw = std::fs::read_to_string(input_path(&path, context))?;
                        Ok::<_, Box<dyn std::error::Error>>(
                            ken_models::RetrievalProfile::from_json_with_upgrade(&raw, true)?,
                        )
                    })
                    .transpose()?;
                let installed = SearchInstallation::open(&installation)?;
                let legacy = installed.legacy_runtime();
                let app = ken_maintenance::RetrievalApplication::new(installed.grammars());
                let loader = Rc::new(ken_index::encoder::ModelEncoderLoader {
                    factory: host.factory(&installation)?,
                    legacy: legacy.clone(),
                });
                let report = app.index(&path, profile, legacy, loader)?;
                if as_json {
                    json_output(&report, 0)
                } else {
                    Ok(output(
                        0,
                        format!(
                            "Prepared {} source passages; profile {}.\n",
                            report["passages"],
                            report["profile_version"].as_str().unwrap_or("")
                        ),
                        String::new(),
                    ))
                }
            }
            RetrievalCommand::Prepare {
                path,
                json: as_json,
            } => {
                let path = input_path(&path, context);
                let installed = SearchInstallation::open(&installation)?;
                let app = ken_maintenance::RetrievalApplication::new(installed.grammars());
                let mut best = installed.into_search();
                let report = app.prepare(&path, &mut best)?;
                if as_json {
                    json_output(&report, 0)
                } else {
                    Ok(output(
                        0,
                        format!(
                            "Prepared best search: {} files, {} owners.\n",
                            report["indexed_files"], report["owners"]
                        ),
                        String::new(),
                    ))
                }
            }
        },
        MaintenanceCommand::Bench {
            dataset,
            engine,
            responses,
            roots,
            gate,
            path,
            top,
            max_chars,
            fail_under_case_recall,
            fail_under_expected_file_recall,
            explain_misses,
            json: as_json,
        } => {
            let dataset = input_path(&dataset, context);
            match engine {
                BenchEngine::Retrieval => {
                    let (Some(responses), Some(roots)) = (responses, roots) else {
                        return Ok(failure(
                            2,
                            "retrieval scoring requires --responses and --roots",
                        ));
                    };
                    let responses = input_path(&responses, context);
                    let roots = input_path(&roots, context);
                    let gate = gate.map(|path| input_path(&path, context));
                    match ken_maintenance::retrieval_benchmark::evaluate_files(
                        &dataset,
                        &roots,
                        &responses,
                        gate.as_deref(),
                    ) {
                        Ok((report, code)) => Ok(output(
                            code,
                            serde_json::to_string(&report)? + "\n",
                            String::new(),
                        )),
                        Err(error) => {
                            Ok(failure(2, format!("invalid retrieval evaluation: {error}")))
                        }
                    }
                }
                BenchEngine::Context => {
                    let paths = project(&path, context, true)?;
                    if !paths.db().is_file() {
                        return Ok(failure(
                            1,
                            format!("no ken index at {}", paths.root().display()),
                        ));
                    }
                    let dataset = ken_maintenance::BenchDataset::from_jsonl(
                        &std::fs::read_to_string(dataset)?,
                    )?;
                    let mut store = ken_store::ProjectStore::open(&paths)?;
                    store.initialize()?;
                    let connection = store.database().connection();
                    let mut runner = LazyContext {
                        connection,
                        root: paths.root().into(),
                        installation,
                        host,
                        encoder: None,
                        numerics: Default::default(),
                    };
                    let report = ken_maintenance::benchmark(
                        connection,
                        paths.root(),
                        &dataset,
                        &ken_maintenance::BenchOptions {
                            top,
                            max_chars: (max_chars > 0).then_some(max_chars),
                            verify_index: true,
                            fail_under_case_recall,
                            fail_under_expected_file_recall,
                            explain_misses,
                        },
                        &mut runner,
                    )?;
                    let code = u8::from(!report.ok);
                    if as_json {
                        json_output(&report, code)
                    } else {
                        let stderr = report
                            .failures
                            .iter()
                            .map(|message| format!("FAIL: {message}\n"))
                            .collect();
                        Ok(output(code, benchmark_text(&report), stderr))
                    }
                }
            }
        }
    }
}
