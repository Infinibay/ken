//! Standalone validation driver: blocks only through the ordinary progress callback.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::{ProjectStore, compact, migrate_inline};
use std::{
    io::{self, Write},
    path::PathBuf,
};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let root = PathBuf::from(args.next().ok_or("expected explicit fixture project")?);
    let phase = args
        .next()
        .ok_or("expected progress phase or recover")?
        .into_string()
        .map_err(|_| "phase must be UTF8")?;
    let paths = ProjectPaths::at(
        &root,
        &DiscoveryContext {
            cwd: std::env::current_dir()?,
            forced_root: None,
            home: None,
        },
    )?;
    let mut project = ProjectStore::open(&paths)?;
    project.initialize()?;
    if phase != "recover" {
        let mut progress = |event| {
            let value = serde_json::to_value(event).expect("event serialization");
            println!("{value}");
            io::stdout().flush().expect("progress output");
            if value["phase"] == phase {
                let mut line = String::new();
                io::stdin()
                    .read_line(&mut line)
                    .expect("controller barrier");
            }
        };
        if matches!(phase.as_str(), "migrated" | "migrate_resume") {
            migrate_inline(&mut project, 2, None, 1, &mut progress)?;
        } else {
            compact(&mut project, 2, &mut progress)?;
        }
    }
    println!("{{\"recovered\":true}}");
    Ok(())
}
