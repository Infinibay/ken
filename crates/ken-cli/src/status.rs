//! Public status presentation; inventories stay in JSON, human text stays concise.
use ken_core::status::StatusReport;
use serde_json::{Value, json};
use std::fmt::Write;

#[derive(Debug)]
pub struct CommandOutput {
    pub code: u8,
    pub stdout: String,
    pub stderr: String,
}
pub type OutputError = serde_json::Error;

pub fn render(report: &StatusReport, as_json: bool) -> Result<CommandOutput, OutputError> {
    let code = if matches!(report, StatusReport::MissingProject { .. }) {
        1
    } else {
        0
    };
    if as_json {
        let mut data = match report {
            StatusReport::MissingProject { error } => json!({"ok":false,"error":error}),
            StatusReport::MetadataOnly(p) => serde_json::to_value(p)?,
            StatusReport::Installed(p) => serde_json::to_value(p)?,
        };
        if code == 0 {
            data["ok"] = true.into();
            data["installed"] = matches!(report, StatusReport::Installed(_)).into();
        }
        return Ok(CommandOutput {
            code,
            stdout: serde_json::to_string_pretty(&data)? + "\n",
            stderr: String::new(),
        });
    }
    if let StatusReport::MissingProject { error } = report {
        return Ok(CommandOutput {
            code,
            stdout: String::new(),
            stderr: format!("{error}\nhint: `ken install .` from a project root\n"),
        });
    }
    let project = match report {
        StatusReport::MetadataOnly(p) => p,
        StatusReport::Installed(p) => &p.project,
        StatusReport::MissingProject { .. } => unreachable!("handled missing project"),
    };
    let mut stdout = format!("project_root  : {}\n", project.project_root.display());
    let StatusReport::Installed(report) = report else {
        stdout.push_str("(no DB yet — run `ken install .`)\n");
        return Ok(CommandOutput {
            code,
            stdout,
            stderr: String::new(),
        });
    };
    let c = &report.counts;
    // Writing to a String cannot fail; formatting has no external side effects.
    let _ = writeln!(
        stdout,
        "files indexed : {} ({} embedded)",
        c.files, c.files_embedded
    );
    let _ = writeln!(
        stdout,
        "symbols       : {} ({} embedded)",
        c.symbols, c.symbols_embedded
    );
    let health = &report.index_health;
    if health.stale_files > 0 {
        let suffix = if health.sample.is_empty() {
            String::new()
        } else {
            format!(" ({})", health.sample.join(", "))
        };
        let _ = writeln!(
            stdout,
            "index health  : {} stale files{suffix}",
            health.stale_files
        );
    }
    let coverage = &report.embedding_coverage;
    if coverage.total > 0 {
        let _ = writeln!(
            stdout,
            "embedding cov : {}/{} ({:.1}%)",
            coverage.embedded, coverage.total, coverage.percent
        );
    }
    for rec in &report.recommendations {
        if !["submit at least", "let hooks run", "save reusable"]
            .iter()
            .any(|prefix| rec.starts_with(prefix))
        {
            let _ = writeln!(stdout, "recommendation: {rec}");
        }
    }
    if !report.daemon.get("running").is_some_and(truthy) {
        stdout.push_str("daemon        : stopped\n");
    } else {
        let sessions = report
            .daemon
            .get("sessions_active")
            .map(scalar_text)
            .unwrap_or_else(|| "0".into());
        let idle = report
            .daemon
            .get("idle_s")
            .map(scalar_text)
            .unwrap_or_else(|| "?".into());
        let _ = writeln!(
            stdout,
            "daemon        : running (sessions={sessions}, idle={idle}s)"
        );
    }
    Ok(CommandOutput {
        code,
        stdout,
        stderr: String::new(),
    })
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
fn scalar_text(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        v => v.to_string(),
    }
}
