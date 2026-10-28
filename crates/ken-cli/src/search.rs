//! CLI options select the shared public application and its output representation.
use crate::{
    args::{PieceKind, Purpose, ResponseFormat, SearchArgs},
    status::CommandOutput,
};
use ken_core::project::DiscoveryContext;
use ken_retrieval::query::{SearchOptions, SearchRequest};
use ken_search::public::{ApplicationError, SearchApplication, resolve_index};
use std::path::PathBuf;

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
        return Ok(failure(
            "this compatibility response mode is not available in the native command yet",
        ));
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
