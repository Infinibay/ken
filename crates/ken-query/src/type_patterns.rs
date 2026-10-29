//! Source type matchers use an explicit continuation stack, including function types.
use crate::{
    ParseError, Result,
    ast::{Expr, MAX_AST_DEPTH, Span},
    parser::Parser,
};
enum Stage {
    Generic,
    FunctionArguments,
    FunctionResult,
}
struct Frame {
    start: Span,
    name: String,
    args: Vec<Expr>,
    stage: Stage,
}
impl Parser<'_> {
    pub fn type_argument(&mut self) -> Result<Expr> {
        let mut frames = Vec::<Frame>::new();
        let mut value: Option<Expr> = None;
        loop {
            if value.is_none() {
                if frames.len() >= MAX_AST_DEPTH {
                    return Err(ParseError::resource(
                        "syntax nesting limit exceeded",
                        self.here()?,
                    ));
                }
                let start = self.here()?;
                let token = self.peek()?;
                if matches!(token.as_str(), "_" | "...") {
                    let t = self.take()?;
                    value = Some(Expr::checked(
                        "wildcard".into(),
                        t.span,
                        t.text,
                        vec![],
                        vec![],
                    )?);
                } else if self.accept("(")? {
                    let mut frame = Frame {
                        start,
                        name: String::new(),
                        args: vec![],
                        stage: Stage::FunctionArguments,
                    };
                    if self.peek()? == ")" {
                        self.expect(")")?;
                        self.expect("->")?;
                        frame.stage = Stage::FunctionResult;
                    }
                    frames.push(frame);
                    continue;
                } else {
                    let name = self.qualified()?;
                    if self.accept("<")? {
                        frames.push(Frame {
                            start,
                            name,
                            args: vec![],
                            stage: Stage::Generic,
                        });
                        continue;
                    }
                    value = Some(Expr::checked(
                        "source_type".into(),
                        self.span(&start),
                        name,
                        vec![],
                        vec![],
                    )?);
                }
            }
            let child = value.take().unwrap();
            let Some(mut frame) = frames.pop() else {
                return Ok(child);
            };
            frame.args.push(child);
            match frame.stage {
                Stage::FunctionResult => {
                    value = Some(Expr::checked(
                        "function_type".into(),
                        self.span(&frame.start),
                        String::new(),
                        frame.args,
                        vec![],
                    )?)
                }
                Stage::Generic | Stage::FunctionArguments => {
                    if self.accept(",")? {
                        frames.push(frame);
                        continue;
                    }
                    match frame.stage {
                        Stage::Generic => {
                            self.expect(">")?;
                            value = Some(Expr::checked(
                                "source_type".into(),
                                self.span(&frame.start),
                                frame.name,
                                frame.args,
                                vec![],
                            )?);
                        }
                        Stage::FunctionArguments => {
                            self.expect(")")?;
                            self.expect("->")?;
                            frame.stage = Stage::FunctionResult;
                            frames.push(frame);
                        }
                        Stage::FunctionResult => unreachable!(),
                    }
                }
            }
        }
    }
}
