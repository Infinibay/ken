//! BODY dispatch has a small stack frame; each production owns its construction.
use crate::{
    Result,
    ast::*,
    parser::{Parser, quote},
};
impl Parser<'_> {
    pub fn body_clause(&mut self, word: &str, start: &Span) -> Result<Clause> {
        self.call_enter()?;
        let result = match word {
            "macro" => self.form_body_macro(word, start),
            "initializer" => self.form_body_initializer(word, start),
            "adjacent" => self.form_body_adjacent(word, start),
            "let" => self.form_body_let(word, start),
            "clear" => self.form_body_clear(word, start),
            "call" => self.form_body_call(word, start),
            "resume" => self.form_body_resume(word, start),
            "return" | "throw" | "yield" | "await" | "break" | "continue" => {
                self.form_body_jump(word, start)
            }
            "if" | "while" => self.form_body_conditional(word, start),
            "insert" => self.form_body_insert(word, start),
            "for" => self.form_body_for(word, start),
            "try" => self.form_body_try(word, start),
            "iterate" => self.form_body_iterate(word, start),
            "spawn" | "join" | "acquire" | "release" => self.form_body_task(word, start),
            "send" | "receive" => self.form_body_channel(word, start),
            _ if word.starts_with('$') => self.form_body_assignment(word, start),
            _ => return Err(self.fail(format!("unknown BODY instruction {}", quote(word)))),
        };
        self.call_depth -= 1;
        result
    }
}
