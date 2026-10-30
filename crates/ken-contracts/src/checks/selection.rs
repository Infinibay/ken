use super::{Result, Rule, SourceInputs, invalid, model::relative};
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    io::Read,
    path::Path,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};
pub fn overlaps(first: &str, second: &str) -> Result<bool> {
    let a = relative(first)?;
    let b = relative(second)?;
    Ok(a == "."
        || b == "."
        || a == b
        || a.starts_with(&(b.clone() + "/"))
        || b.starts_with(&(a + "/")))
}
fn git(root: &Path, args: &[&str], check: &mut dyn FnMut() -> Result<()>) -> Result<Vec<String>> {
    check()?;
    let mut child = Command::new(ken_core::native_program::git_program()?)
        .arg("-C")
        .arg(root)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| invalid("Git stdout unavailable"))?;
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout.take(16000001).read_to_end(&mut bytes).map(|_| bytes)
    });
    let start = Instant::now();
    let status = loop {
        if let Err(error) = check() {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err(error);
        }
        match child.try_wait()? {
            Some(status) => break status,
            None if start.elapsed() >= Duration::from_secs(5) => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = reader.join();
                return Err(invalid("changes scope requires a Git worktree with HEAD"));
            }
            None => thread::sleep(Duration::from_millis(5)),
        }
    };
    let data = reader
        .join()
        .map_err(|_| invalid("Git output worker panicked"))??;
    if !status.success() || data.len() > 16000000 {
        return Err(invalid("changes scope requires a Git worktree with HEAD"));
    }
    let text =
        String::from_utf8(data).map_err(|_| invalid("Git returned non-UTF-8 source paths"))?;
    Ok(text
        .split('\0')
        .filter(|p| !p.is_empty())
        .map(str::to_owned)
        .collect())
}
pub fn changed_paths(root: &Path) -> Result<Vec<String>> {
    changed_paths_checked(root, &mut || Ok(()))
}
pub fn changed_paths_checked(
    root: &Path,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<Vec<String>> {
    let mut files = git(
        root,
        &["diff", "HEAD", "--name-only", "--no-renames", "-z", "--"],
        check,
    )?;
    files.extend(git(
        root,
        &["ls-files", "--others", "--exclude-standard", "-z"],
        check,
    )?);
    let mut paths = BTreeSet::new();
    for path in files {
        check()?;
        if !path.split('/').any(|p| p == ".ken" || p == ".git") {
            relative(&path)?;
            paths.insert(path);
        }
    }
    Ok(paths.into_iter().collect())
}
pub fn affected(
    root: &Path,
    records: &[Value],
    changed: &[String],
    budget: Duration,
    include_deleted: bool,
    inputs: &mut dyn SourceInputs,
) -> Result<(BTreeSet<String>, Value)> {
    let started = Instant::now();
    let mut selected = BTreeSet::new();
    let mut evidence = serde_json::Map::new();
    inputs.checkpoint()?;
    for record in records {
        inputs.checkpoint()?;
        let rule = Rule::read(&record["definition"])?;
        let mut direct = false;
        for path in changed {
            if overlaps(&rule.path, path)? {
                direct = true;
                break;
            }
        }
        if direct {
            selected.insert(rule.id.clone());
            evidence.insert(rule.id, json!({"basis":"declared_scope"}));
            continue;
        }
        let result = (|| -> Result<Option<Value>> {
            let remaining = budget
                .checked_sub(started.elapsed())
                .filter(|b| !b.is_zero())
                .ok_or_else(|| invalid("selection budget exhausted"))?;
            let snapshot = inputs.capture(root, &rule.path, remaining)?;
            let remaining = budget
                .saturating_sub(started.elapsed())
                .max(Duration::from_millis(1));
            let deps = inputs.dependencies(root, &snapshot, remaining)?;
            let mut hits = Vec::new();
            for item in deps["manifest"]
                .as_array()
                .ok_or_else(|| invalid("dependency manifest unavailable"))?
            {
                let path = item[0]
                    .as_str()
                    .ok_or_else(|| invalid("invalid dependency manifest"))?;
                for changed in changed {
                    if overlaps(path, changed)? {
                        hits.push(path.to_owned());
                        break;
                    }
                }
            }
            let missing = changed
                .iter()
                .filter(|p| include_deleted && !root.join(p).exists())
                .cloned()
                .collect::<Vec<_>>();
            let issues = deps.get("issues").cloned().unwrap_or(json!([]));
            if !hits.is_empty() || !missing.is_empty() || super::wire::truth(&issues) {
                Ok(Some(
                    json!({"basis":if !hits.is_empty(){"import_dependency"}else{"conservative"},"paths":if !hits.is_empty(){hits}else{missing},"issues":issues}),
                ))
            } else {
                Ok(None)
            }
        })();
        match result {
            Ok(None) => {}
            Ok(Some(detail)) => {
                selected.insert(rule.id.clone());
                evidence.insert(rule.id, detail);
            }
            Err(e) => {
                selected.insert(rule.id.clone());
                evidence.insert(
                    rule.id,
                    json!({"basis":"conservative","reason":e.to_string()}),
                );
            }
        }
    }
    inputs.checkpoint()?;
    Ok((selected, Value::Object(evidence)))
}
