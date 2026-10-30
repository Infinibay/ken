use super::*;
use crate::{Program, Step, ast::Expr};
#[derive(Clone, Debug)]
pub struct SyntaxPlan {
    pub(super) program: Program,
    pub(super) steps: Vec<Step>,
    pub(super) links: Vec<(String, String, bool)>,
    pub(super) branches: Vec<SyntaxPlan>,
}
/// One projection of the supported checked-program representations. Explicit
/// steps are authoritative; older producers supply scans plus actions/filters.
/// Admission, optimizer barriers and execution all consume this projection.
pub(crate) fn effective_steps(program: &Program) -> Vec<Step> {
    if !program.steps.is_empty() {
        return program.steps.clone();
    }
    let mut steps = program
        .scans
        .iter()
        .cloned()
        .map(Step::Scan)
        .collect::<Vec<_>>();
    if program.actions.is_empty() {
        steps.extend(program.filters.iter().cloned().map(|expression| {
            Step::Action(crate::Action {
                role: String::new(),
                expression,
            })
        }));
    } else {
        steps.extend(
            program
                .actions
                .iter()
                .cloned()
                .map(|(role, expression)| Step::Action(crate::Action { role, expression })),
        );
    }
    steps
}

pub(super) fn may_fail(e: &Expr) -> bool {
    e.kind == "regex"
        || e.kind == "binary" && matches!(e.value.as_str(), "+" | "-" | "*" | "/" | "%" | "matches")
        || e.kind == "unary" && e.value != "not"
        || e.args.iter().any(may_fail)
}
pub(super) fn atoms<'a>(e: &'a Expr, out: &mut Vec<&'a Expr>) {
    if e.kind == "binary" && e.value == "and" {
        for a in &e.args {
            atoms(a, out);
        }
    } else {
        out.push(e);
    }
}
pub(super) fn links<'a>(
    expressions: impl Iterator<Item = &'a Expr>,
) -> Vec<(String, String, bool)> {
    let mut out = vec![];
    for e in expressions {
        let mut a = vec![];
        atoms(e, &mut a);
        for e in a {
            if e.kind == "call"
                && matches!(e.value.as_str(), "contains" | "contains_direct" | "owns")
            {
                let args = e
                    .args
                    .iter()
                    .filter_map(|a| a.args.first())
                    .collect::<Vec<_>>();
                if args.len() == 2 && args.iter().all(|a| a.kind == "role") {
                    out.push((
                        args[0].value.clone(),
                        args[1].value.clone(),
                        e.value != "contains",
                    ));
                }
            }
        }
    }
    out
}
impl SyntaxPlan {
    pub fn program(&self) -> &Program {
        &self.program
    }
    pub fn compile(program: &Program) -> Result<Self> {
        crate::authoring::explain(
            &crate::CompiledQuery {
                program: program.clone(),
                relational: None,
            },
            "exploration",
        )
        .map_err(|e| ExecutionError::Unsupported(e.to_string()))?;
        let steps = effective_steps(program);
        let barrier = steps.iter().any(|s| match s {
            Step::Action(a) => may_fail(&a.expression),
            Step::Scan(s) => s.properties.iter().any(|(_, e)| may_fail(e)),
            Step::Body(_) => false,
        });
        let relations = if barrier {
            vec![]
        } else {
            links(steps.iter().filter_map(|s| {
                if let Step::Action(a) = s {
                    a.role.is_empty().then_some(&a.expression)
                } else {
                    None
                }
            }))
        };
        Ok(Self {
            program: program.clone(),
            steps,
            links: relations,
            branches: program
                .branches
                .iter()
                .map(Self::compile)
                .collect::<Result<_>>()?,
        })
    }
}
