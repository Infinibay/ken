//! Ordinary terminal memory commands share application policy with MCP tools.
use crate::status::CommandOutput;
use clap::{Subcommand, ValueEnum};
use ken_core::project::{DiscoveryContext, ProjectPaths, locate_project};
use ken_knowledge::findings;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
#[derive(Debug, Subcommand)]
pub enum MemoryCommand {
    /// Save a reusable finding, retaining content if optional encoding fails
    Remember {
        topic: String,
        content: String,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long = "tag")]
        tags: Vec<String>,
        #[arg(long, value_enum)]
        kind: Option<FindingKind>,
        #[arg(long)]
        json: bool,
    },
    /// Delete a finding by exact topic
    Forget {
        topic: String,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
    /// List recent findings
    Findings {
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(short = 'n', long, default_value_t = 20, allow_hyphen_values = true)]
        limit: i64,
        #[arg(long)]
        tag: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// Search saved findings using this project's query embedding space
    Recall {
        #[arg(required=true,num_args=1..)]
        query: Vec<String>,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(short = 'n', long, default_value_t = 5, allow_hyphen_values = true)]
        limit: i64,
        #[arg(long, default_value_t = 0.25, allow_hyphen_values = true)]
        min_score: f64,
        #[arg(long)]
        json: bool,
    },
    /// Find graph neighbors of an exact or semantically resolved topic
    RelatedFindings {
        topic: String,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(short = 'n', long, default_value_t = 8, allow_hyphen_values = true)]
        limit: i64,
        #[arg(long, default_value_t = 0.3, allow_hyphen_values = true)]
        min_weight: f64,
        #[arg(long)]
        json: bool,
    },
    /// Find notes which reference a source file
    FileFindings {
        file: String,
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(short = 'n', long, default_value_t = 15, allow_hyphen_values = true)]
        limit: i64,
        #[arg(long)]
        expand: bool,
        #[arg(long)]
        json: bool,
    },
    /// Maintain the derived findings graph
    FindingsGraph {
        #[command(subcommand)]
        command: GraphCommand,
    },
}
#[derive(Debug, Clone, Copy, ValueEnum)]
#[value(rename_all = "snake_case")]
pub enum FindingKind {
    Finding,
    PersistentRule,
    ExperimentalFinding,
    Hypothesis,
}
impl FindingKind {
    fn name(self) -> &'static str {
        match self {
            Self::Finding => "finding",
            Self::PersistentRule => "persistent_rule",
            Self::ExperimentalFinding => "experimental_finding",
            Self::Hypothesis => "hypothesis",
        }
    }
}
#[derive(Debug, Subcommand)]
pub enum GraphCommand {
    Rebuild {
        #[arg(long, default_value = ".")]
        path: PathBuf,
        #[arg(long)]
        json: bool,
    },
}
impl MemoryCommand {
    fn path(&self) -> &Path {
        match self {
            Self::Remember { path, .. }
            | Self::Forget { path, .. }
            | Self::Findings { path, .. }
            | Self::Recall { path, .. }
            | Self::RelatedFindings { path, .. }
            | Self::FileFindings { path, .. } => path,
            Self::FindingsGraph {
                command: GraphCommand::Rebuild { path, .. },
            } => path,
        }
    }
}
fn output(code: u8, stdout: String, stderr: String) -> CommandOutput {
    CommandOutput {
        code,
        stdout,
        stderr,
    }
}
fn line(value: impl AsRef<str>) -> String {
    format!("{}\n", value.as_ref())
}
fn pretty(value: &Value) -> Result<String, serde_json::Error> {
    serde_json::to_string_pretty(value).map(line)
}
fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}
fn paths(
    start: &Path,
    context: &DiscoveryContext,
) -> Result<ProjectPaths, Box<dyn std::error::Error>> {
    Ok(match locate_project(start, context)? {
        Some(paths) => paths,
        None => ProjectPaths::at(start, context)?,
    })
}
/// Ordinary commands preserve their own exit and presentation contract, while
/// construction and domain policies remain shared with consolidated tool calls.
pub fn run(
    command: MemoryCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> CommandOutput {
    match execute(command, installation, context) {
        Ok(output) => output,
        Err(error) => output(1, String::new(), format!("error: {error}\n")),
    }
}
fn execute(
    command: MemoryCommand,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    let paths = paths(command.path(), context)?;
    if !paths.db().is_file() {
        return Ok(output(
            1,
            String::new(),
            format!("error: no .ken project at {}\n", paths.root().display()),
        ));
    }
    let app =
        crate::tools::knowledge_application(&paths, installation).map_err(std::io::Error::other)?;
    // Opening an already present project is ordinary host work, not installation.
    let store = ken_store::ProjectStore::open(&paths)?;
    let db = store.database().connection();
    let now = now();
    match command {
        MemoryCommand::Remember {
            topic,
            content,
            tags,
            kind,
            json: as_json,
            ..
        } => {
            let value=app.remember(db,&json!({"topic":topic,"content":content,"tags":tags,"kind":kind.map(FindingKind::name)}),now)?;
            let ok = value["ok"] == true;
            Ok(if as_json {
                output(u8::from(!ok), pretty(&value)?, String::new())
            } else if ok {
                output(
                    0,
                    line(format!(
                        "remembered: {}",
                        value["topic"].as_str().unwrap_or("")
                    )),
                    String::new(),
                )
            } else {
                output(
                    1,
                    String::new(),
                    line(format!(
                        "error: {}",
                        value["error"].as_str().unwrap_or("remember failed")
                    )),
                )
            })
        }
        MemoryCommand::Forget {
            topic,
            json: as_json,
            ..
        } => {
            let value = app.remember(db, &json!({"action":"forget","topic":topic}), now)?;
            let deleted = value["deleted"].as_u64().unwrap_or(0) > 0;
            Ok(if as_json {
                output(u8::from(!deleted), pretty(&value)?, String::new())
            } else if deleted {
                output(
                    0,
                    line(format!("forgot: {}", value["topic"].as_str().unwrap_or(""))),
                    String::new(),
                )
            } else {
                output(
                    1,
                    String::new(),
                    line(format!(
                        "not found: {}",
                        value["topic"].as_str().unwrap_or("")
                    )),
                )
            })
        }
        MemoryCommand::Findings {
            limit,
            tag,
            json: as_json,
            ..
        } => {
            let value = app.recall(
                db,
                &json!({"limit":limit,"tag":tag.unwrap_or_default()}),
                now,
            )?;
            let hits = checked_hits(&value)?;
            let rendered = findings::format_recall_hits(hits);
            Ok(output(
                0,
                if as_json {
                    pretty(&value)?
                } else if rendered.is_empty() {
                    String::new()
                } else {
                    line(rendered)
                },
                String::new(),
            ))
        }
        MemoryCommand::Recall {
            query,
            limit,
            min_score,
            json: as_json,
            ..
        } => {
            let query = query.join(" ");
            let value = app.recall_findings(db, &query, limit.max(1) as usize, Some(min_score))?;
            let hits = checked_hits(&value)?;
            let rendered = findings::format_recall_hits(hits);
            Ok(output(
                0,
                if as_json {
                    pretty(&json!(hits))?
                } else if rendered.is_empty() {
                    line(format!(
                        "no relevant findings (min_score={})",
                        float3(min_score)
                    ))
                } else {
                    line(rendered)
                },
                String::new(),
            ))
        }
        MemoryCommand::RelatedFindings {
            topic,
            limit,
            min_weight,
            json: as_json,
            ..
        } => {
            let value = app.related_findings(db, &topic, limit.max(1) as usize, min_weight, now)?;
            if as_json {
                return Ok(output(0, pretty(&value)?, String::new()));
            }
            let neighbors = value["neighbors"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or_default();
            let text = if neighbors.is_empty() {
                value["note"]
                    .as_str()
                    .unwrap_or("no related findings")
                    .to_owned()
            } else {
                neighbors
                    .iter()
                    .map(|neighbor| {
                        let links = neighbor["edges"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .map(|edge| {
                                format!(
                                    "{} {:.2}",
                                    edge["type"].as_str().unwrap_or(""),
                                    edge["weight"].as_f64().unwrap_or(0.)
                                )
                            })
                            .collect::<Vec<_>>()
                            .join(", ");
                        format!(
                            "{:.2}  {}  [{links}]",
                            neighbor["best_weight"].as_f64().unwrap_or(0.),
                            neighbor["topic"].as_str().unwrap_or("")
                        )
                    })
                    .collect::<Vec<_>>()
                    .join("\n")
            };
            Ok(output(0, line(text), String::new()))
        }
        MemoryCommand::FileFindings {
            file,
            limit,
            expand,
            json: as_json,
            ..
        } => {
            let value = app.file_findings(db, &file, expand, limit.max(1) as usize, now)?;
            if as_json {
                return Ok(output(0, pretty(&value)?, String::new()));
            }
            let findings = value["findings"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or_default();
            let mut lines = if findings.is_empty() {
                vec![
                    value["note"]
                        .as_str()
                        .unwrap_or("no findings reference this file")
                        .into(),
                ]
            } else {
                findings
                    .iter()
                    .map(|finding| {
                        format!(
                            "{}\n    {}",
                            finding["topic"].as_str().unwrap_or(""),
                            finding["content"].as_str().unwrap_or("")
                        )
                    })
                    .collect::<Vec<String>>()
            };
            if !findings.is_empty() {
                lines.extend(
                    value["related"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .map(|related| {
                            format!(
                                "~ {} ({:.2})",
                                related["topic"].as_str().unwrap_or(""),
                                related["weight"].as_f64().unwrap_or(0.)
                            )
                        }),
                );
            }
            Ok(output(0, line(lines.join("\n")), String::new()))
        }
        MemoryCommand::FindingsGraph {
            command: GraphCommand::Rebuild { json: as_json, .. },
        } => {
            let value = match app.rebuild_findings_graph(db, now) {
                Ok(value) => value,
                Err(error) => {
                    return Ok(output(
                        1,
                        String::new(),
                        line(format!("error: rebuild failed: {error}")),
                    ));
                }
            };
            Ok(output(
                0,
                if as_json {
                    pretty(&value)?
                } else {
                    line(format!(
                        "findings graph rebuilt: {} refs, {} edges",
                        value["refs"], value["edges"]
                    ))
                },
                String::new(),
            ))
        }
    }
}
fn checked_hits(value: &Value) -> Result<&[Value], Box<dyn std::error::Error>> {
    value.as_array().map(Vec::as_slice).ok_or_else(|| {
        std::io::Error::other(
            value["error"]
                .as_str()
                .unwrap_or("memory response is not a findings list"),
        )
        .into()
    })
}
fn float3(value: f64) -> String {
    if value.is_nan() {
        "nan".into()
    } else if value == f64::INFINITY {
        "inf".into()
    } else if value == f64::NEG_INFINITY {
        "-inf".into()
    } else {
        format!("{value:.3}")
    }
}
