//! CLI names project discovery separately from a tool's source selection.
use clap::{Args, Subcommand};
use serde_json::{Value, json};
#[derive(Debug, Subcommand)]
pub enum KnowledgeCommand {
    #[command(alias = "ken_remember")]
    Remember(Remember),
    #[command(alias = "ken_recall")]
    Recall(Recall),
    #[command(alias = "ken_reason_record")]
    ReasonRecord(ReasonRecord),
    #[command(alias = "ken_reason")]
    Reason(Reason),
    #[command(alias = "ken_who")]
    Who(Who),
}
#[derive(Debug, Args)]
pub struct Remember {
    #[command(flatten)]
    pub project: crate::args::ToolProjectPath,
    pub topic: String,
    #[arg(long, default_value = "")]
    pub content: String,
    #[arg(long, default_value = "save")]
    pub action: String,
    #[arg(long,num_args=0..)]
    pub tags: Option<Vec<String>>,
    #[arg(long, default_value = "")]
    pub reason: String,
    #[command(flatten)]
    pub anchors: Anchors,
    #[arg(long)]
    pub justification: Option<String>,
    #[arg(long, default_value = "")]
    pub check_run: String,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Default, Args)]
pub struct Anchors {
    #[arg(long, default_value = "")]
    pub anchor_file: String,
    #[arg(long, default_value = "")]
    pub anchor_symbol: String,
    #[arg(long, default_value = "")]
    pub anchor_tool: String,
    #[arg(long, default_value = "")]
    pub anchor_error: String,
}
#[derive(Debug, Args)]
pub struct Recall {
    #[arg(long, default_value = "")]
    pub query: String,
    #[arg(long = "path", alias = "source-path", default_value = "")]
    pub source_path: String,
    #[arg(long, default_value = "")]
    pub topic: String,
    #[arg(long, default_value = "")]
    pub tag: String,
    #[arg(long, default_value_t = 5, allow_hyphen_values = true)]
    pub limit: i64,
    #[arg(long, default_value_t = 0., allow_hyphen_values = true)]
    pub min_score: f64,
    #[command(flatten)]
    pub anchors: Anchors,
    #[arg(long, default_value = "full")]
    pub detail: String,
    #[arg(long, default_value_t = 3000, allow_hyphen_values = true)]
    pub max_chars: i64,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct ReasonRecord {
    #[command(flatten)]
    pub project: crate::args::ToolProjectPath,
    pub source: String,
    #[arg(long,num_args=0..)]
    pub facts: Option<Vec<String>>,
    #[arg(long,num_args=0..)]
    pub rules: Option<Vec<String>>,
    #[arg(long, default_value = "")]
    pub evidence: String,
    #[arg(long, default_value = "main")]
    pub context: String,
    #[arg(long, overrides_with = "no_retract")]
    pub retract: bool,
    #[arg(long, overrides_with = "retract")]
    pub no_retract: bool,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct Reason {
    #[command(flatten)]
    pub project: crate::args::ToolProjectPath,
    pub question: String,
    #[arg(long)]
    pub goal: Option<String>,
    #[arg(long, default_value = "main")]
    pub context: String,
    #[arg(long, default_value_t = 1000, allow_hyphen_values = true)]
    pub budget: i64,
    #[arg(long, default_value_t = 7, allow_hyphen_values = true)]
    pub seed: i64,
    #[arg(long,num_args=0..)]
    pub assumptions: Option<Vec<String>>,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
#[derive(Debug, Args)]
pub struct Who {
    pub question: String,
    #[arg(long = "path", alias = "source-path", default_value = ".")]
    pub source_path: String,
    #[arg(long,num_args=0..)]
    pub hypotheses: Option<Vec<String>>,
    #[arg(long, default_value_t = 3, allow_hyphen_values = true)]
    pub limit: i64,
    #[arg(long, overrides_with = "no_include_tests")]
    pub include_tests: bool,
    #[arg(long, overrides_with = "include_tests")]
    pub no_include_tests: bool,
    #[arg(long, overrides_with = "no_full")]
    pub full: bool,
    #[arg(long, overrides_with = "full")]
    pub no_full: bool,
    #[arg(long,default_value_t=true,action=clap::ArgAction::Set,num_args=0..=1,default_missing_value="true",overrides_with="no_verify")]
    pub verify: bool,
    #[arg(long, overrides_with = "verify")]
    pub no_verify: bool,
    #[arg(long, default_value_t = 3000.)]
    pub timeout_ms: f64,
    #[arg(long, default_value = "compact")]
    pub output_format: String,
}
fn parsed(value: Option<String>) -> serde_json::Result<Option<Value>> {
    value.map(|text| serde_json::from_str(&text)).transpose()
}
/// Original object-array flags consume zero or more JSON objects. Retain the
/// native single JSON-array spelling as an additive compatibility form.
fn objects(values: Option<Vec<String>>) -> serde_json::Result<Option<Vec<Value>>> {
    values
        .map(|values| {
            let one = values.len() == 1;
            let mut objects = Vec::new();
            let invalid = || {
                <serde_json::Error as serde::de::Error>::custom(
                    "expected a JSON object, or a single JSON array of objects",
                )
            };
            for text in values {
                match serde_json::from_str::<Value>(&text)? {
                    value @ Value::Object(_) => objects.push(value),
                    Value::Array(items) if one && items.iter().all(Value::is_object) => {
                        objects.extend(items)
                    }
                    _ => return Err(invalid()),
                }
            }
            Ok(objects)
        })
        .transpose()
}
fn anchors(value: &mut Value, a: Anchors) {
    value["anchor_file"] = json!(a.anchor_file);
    value["anchor_symbol"] = json!(a.anchor_symbol);
    value["anchor_tool"] = json!(a.anchor_tool);
    value["anchor_error"] = json!(a.anchor_error);
}
impl KnowledgeCommand {
    pub(crate) fn project_path(&self) -> Option<&std::path::Path> {
        let project = match self {
            Self::Remember(a) => &a.project,
            Self::ReasonRecord(a) => &a.project,
            Self::Reason(a) => &a.project,
            _ => return None,
        };
        project.project_path.as_deref()
    }
    pub(crate) fn source_path(&self) -> Option<&str> {
        match self {
            Self::Recall(a) => Some(&a.source_path),
            Self::Who(a) => Some(&a.source_path),
            _ => None,
        }
    }
    pub fn request(self) -> serde_json::Result<(&'static str, Value)> {
        Ok(match self {
            Self::Remember(a) => {
                let mut value = json!({"topic":a.topic,"content":a.content,"action":a.action,"tags":a.tags,"reason":a.reason,"justification":parsed(a.justification)?,"check_run":a.check_run,"output_format":a.output_format});
                anchors(&mut value, a.anchors);
                ("ken_remember", value)
            }
            Self::Recall(a) => {
                let mut value = json!({"query":a.query,"path":a.source_path,"topic":a.topic,"tag":a.tag,"limit":a.limit,"min_score":a.min_score,"detail":a.detail,"max_chars":a.max_chars,"output_format":a.output_format});
                anchors(&mut value, a.anchors);
                ("ken_recall", value)
            }
            Self::ReasonRecord(a) => (
                "ken_reason_record",
                json!({"source":a.source,"facts":objects(a.facts)?,"rules":objects(a.rules)?,"evidence":a.evidence,"context":a.context,"retract":a.retract,"output_format":a.output_format}),
            ),
            Self::Reason(a) => (
                "ken_reason",
                json!({"question":a.question,"goal":parsed(a.goal)?,"context":a.context,"budget":a.budget,"seed":a.seed,"assumptions":objects(a.assumptions)?,"output_format":a.output_format}),
            ),
            Self::Who(a) => (
                "ken_who",
                json!({"question":a.question,"path":a.source_path,"hypotheses":a.hypotheses,"limit":a.limit,"include_tests":a.include_tests,"full":a.full,"verify":a.verify&&!a.no_verify,"timeout_ms":a.timeout_ms,"output_format":a.output_format}),
            ),
        })
    }
}
