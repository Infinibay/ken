use super::{Lowering, Operation, Region, block, identifier, tokens};
use serde_json::json;
impl Lowering<'_, '_> {
    fn branch(
        &mut self,
        node: &Operation,
        region: &mut Region,
        alternatives: Option<Vec<usize>>,
        depth: usize,
    ) {
        let (condition, consequence) = (
            self.field(node, &["condition"]),
            self.field(node, &["consequence"]),
        );
        let (Some(condition), Some(consequence)) = (condition, consequence) else {
            self.opaque(node, region, "branch-lowering");
            return;
        };
        if depth > 64 {
            self.opaque(node, region, "branch-lowering");
            return;
        }
        let mut arms = vec![self.region(self.node(consequence), "consequence")];
        let rest = alternatives.unwrap_or_else(|| {
            self.children(node)
                .into_iter()
                .filter(|&i| self.node(i).role == "alternative")
                .collect()
        });
        if let Some(&first) = rest.first() {
            let mut alternative = Region::new(
                format!("{}/region/alternative", self.node(first).id),
                "alternative",
            );
            if self.node(first).native_kind == "elif_clause" {
                self.branch(
                    self.node(first),
                    &mut alternative,
                    Some(rest[1..].to_vec()),
                    depth + 1,
                );
            } else if rest.len() == 1 {
                self.statement(self.node(first), &mut alternative, 0);
            } else {
                self.opaque(node, region, "ambiguous-branch-alternatives");
                return;
            }
            arms.push(alternative);
        }
        let value = self.expression(self.node(condition), region, 0);
        self.emit(
            region,
            node,
            "if",
            vec![value],
            false,
            &["unknown"],
            arms,
            json!({"truth":"native"}),
        );
    }
    fn iteration(&mut self, node: &Operation, region: &mut Region) -> bool {
        let kind = node.native_kind.as_str();
        if !matches!(
            kind,
            "for_statement"
                | "for_in_statement"
                | "enhanced_for_statement"
                | "foreach_statement"
                | "for_expression"
        ) {
            return false;
        }
        let native_tokens = tokens(node);
        let language = self.function.language.as_str();
        let supported = (language == "python" && kind == "for_statement")
            || (matches!(language, "javascript" | "typescript")
                && kind == "for_in_statement"
                && native_tokens.iter().any(|t| t == "of"))
            || (language == "java" && kind == "enhanced_for_statement")
            || (language == "csharp" && kind == "foreach_statement")
            || (language == "rust" && kind == "for_expression");
        let (target, source, body) = (
            self.field(node, &["left", "name", "pattern"]),
            self.field(node, &["right", "value"]),
            self.field(node, &["body"]),
        );
        if !supported
            || native_tokens
                .iter()
                .any(|s| matches!(s.as_str(), "async" | "await" | "ref"))
            || self.field(node, &["alternative"]).is_some()
        {
            return false;
        }
        let (Some(target), Some(source), Some(body)) = (target, source, body) else {
            return false;
        };
        if !identifier(self.node(target)) {
            return false;
        }
        let value = self.expression(self.node(source), region, 0);
        let mut repeated = Region::new(format!("{}/region/body", self.node(body).id), "body");
        let item = self
            .emit(
                &mut repeated,
                self.node(target),
                "iteration.value",
                vec![],
                true,
                &["unknown"],
                vec![],
                json!({}),
            )
            .unwrap();
        let place = self.address(self.node(target), &mut repeated);
        if self.function.language != "python" {
            self.emit(
                &mut repeated,
                self.node(target),
                "slot.declare",
                vec![place.clone()],
                false,
                &[],
                vec![],
                json!({}),
            );
        }
        self.emit(
            &mut repeated,
            self.node(target),
            "slot.store",
            vec![place, item],
            false,
            &["write.binding"],
            vec![],
            json!({}),
        );
        self.statement(self.node(body), &mut repeated, 0);
        self.emit(
            region,
            node,
            "iterate",
            vec![value],
            false,
            &["invoke", "unknown"],
            vec![repeated],
            json!({"protocol":"native","element":"value","evaluation":"iterable-once"}),
        );
        true
    }
    pub(super) fn statement(&mut self, node: &Operation, region: &mut Region, depth: usize) {
        if self.active >= 64 {
            self.opaque(node, region, "nesting-limit");
            return;
        }
        self.active += 1;
        self.statement_inner(node, region, depth);
        self.active -= 1;
    }
    fn statement_inner(&mut self, node: &Operation, region: &mut Region, depth: usize) {
        if depth > 64 || node.owner != self.entity.id {
            self.opaque(node, region, "nested-or-deep-region");
            return;
        }
        let children = self.children(node);
        let kind = node.native_kind.as_str();
        if block(node)
            || matches!(
                kind,
                "expression_statement"
                    | "local_variable_declaration"
                    | "local_declaration_statement"
                    | "lexical_declaration"
                    | "variable_declaration"
                    | "declaration"
            )
        {
            for index in children {
                let child = self.node(index);
                if child.role == "type"
                    || matches!(
                        child.native_kind.as_str(),
                        "modifiers" | "predefined_type" | "integral_type"
                    )
                {
                    continue;
                }
                if kind == "declaration" && child.role == "declarator" && identifier(child) {
                    let address = self.address(child, region);
                    self.emit(
                        region,
                        child,
                        "slot.declare",
                        vec![address],
                        false,
                        &[],
                        vec![],
                        json!({}),
                    );
                } else {
                    self.statement(child, region, depth + 1);
                }
            }
        } else if node.kind == "DECLARATION" && kind == "variable_declarator" {
            if let Some(index) = self.field(node, &["name"])
                && identifier(self.node(index))
            {
                let address = self.address(self.node(index), region);
                self.emit(
                    region,
                    node,
                    "slot.declare",
                    vec![address],
                    false,
                    &[],
                    vec![],
                    json!({}),
                );
            } else {
                self.opaque(node, region, "declaration-lowering");
            }
        } else if node.kind == "ASSIGN" || kind == "init_declarator" {
            self.assignment(node, region, children);
        } else if node.kind == "RETURN" {
            let operands = children
                .into_iter()
                .map(|i| self.expression(self.node(i), region, 0))
                .collect();
            self.emit(
                region,
                node,
                "return",
                operands,
                false,
                &[],
                vec![],
                json!({}),
            );
        } else if matches!(kind, "if_statement" | "if_expression") {
            self.branch(node, region, None, 0);
        } else if node.kind == "LOOP" {
            self.loop_statement(node, region, children);
        } else if matches!(kind, "break_statement" | "continue_statement") && children.is_empty() {
            self.emit(
                region,
                node,
                kind.strip_suffix("_statement").unwrap(),
                vec![],
                false,
                &[],
                vec![],
                json!({}),
            );
        } else if node.kind == "THROW" {
            let operands = children
                .into_iter()
                .map(|i| self.expression(self.node(i), region, 0))
                .collect();
            self.emit(
                region,
                node,
                "throw",
                operands,
                false,
                &[],
                vec![],
                json!({}),
            );
        } else if !matches!(kind, "pass_statement" | "empty_statement") {
            self.expression(node, region, 0);
        }
    }
    fn assignment(&mut self, node: &Operation, region: &mut Region, children: Vec<usize>) {
        let left = self.field(node, &["left", "name", "pattern", "declarator"]);
        let mut right = self.field(node, &["right", "value"]);
        let native_tokens = tokens(node);
        if right.is_none()
            && let Some(left) = left
            && self.function.language == "csharp"
            && native_tokens.iter().any(|s| s == "=")
        {
            right = children
                .into_iter()
                .find(|&i| self.node(i).start >= self.node(left).end && i != left);
        }
        let (Some(left), Some(right)) = (left, right) else {
            self.opaque(node, region, "assignment-lowering");
            return;
        };
        if native_tokens
            .iter()
            .any(|t| t.ends_with('=') && !matches!(t.as_str(), "=" | ":="))
        {
            self.opaque(node, region, "assignment-lowering");
            return;
        }
        if matches!(
            node.native_kind.as_str(),
            "variable_declarator" | "init_declarator" | "let_declaration"
        ) && identifier(self.node(left))
        {
            let address = self.address(self.node(left), region);
            self.emit(
                region,
                node,
                "slot.declare",
                vec![address],
                false,
                &[],
                vec![],
                json!({}),
            );
        }
        let (target, value) = if matches!(self.function.language.as_str(), "python" | "cpp") {
            let value = self.expression(self.node(right), region, 0);
            let target = self.address(self.node(left), region);
            (target, value)
        } else {
            let target = self.address(self.node(left), region);
            let value = self.expression(self.node(right), region, 0);
            (target, value)
        };
        let binding = target.kind == "place";
        self.emit(
            region,
            node,
            if binding {
                "slot.store"
            } else {
                "memory.store"
            },
            vec![target, value],
            false,
            if binding {
                &["write.binding"]
            } else {
                &["write.memory", "unknown"]
            },
            vec![],
            json!({}),
        );
    }
    fn loop_statement(&mut self, node: &Operation, region: &mut Region, children: Vec<usize>) {
        if self.field(node, &["alternative"]).is_some() {
            self.opaque(node, region, "loop-exhaustion-clause");
            return;
        }
        if self.iteration(node, region) {
            return;
        }
        let (mut condition, body) = (
            self.field(node, &["condition"]),
            self.field(node, &["body"]),
        );
        let counted = node.native_kind == "for_statement"
            && matches!(
                self.function.language.as_str(),
                "javascript" | "typescript" | "java" | "csharp" | "cpp"
            );
        if counted && condition.is_some_and(|i| self.node(i).native_kind == "empty_statement") {
            condition = None;
        }
        let Some(body) = body else {
            self.opaque(node, region, "loop-lowering");
            return;
        };
        if !counted
            && (condition.is_none()
                || !matches!(
                    node.native_kind.as_str(),
                    "while_statement" | "do_statement"
                ))
        {
            self.opaque(node, region, "loop-lowering");
            return;
        }
        let mut test = Region::new(format!("{}/region/test", node.id), "test");
        let value = if let Some(condition) = condition {
            self.expression(self.node(condition), &mut test, 0)
        } else {
            self.emit(
                &mut test,
                node,
                "const",
                vec![],
                true,
                &[],
                vec![],
                json!({"spelling":"true","native_kind":"true","implicit":true}),
            )
            .unwrap()
        };
        test.outputs = vec![value.r#ref];
        let body = self.region(self.node(body), "body");
        let (regions, form) = if counted {
            let mut init = Region::new(format!("{}/region/init", node.id), "init");
            let mut update = Region::new(format!("{}/region/update", node.id), "update");
            for index in children {
                let child = self.node(index);
                if matches!(child.role.as_str(), "init" | "initializer") {
                    self.statement(child, &mut init, 0);
                } else if matches!(child.role.as_str(), "update" | "increment") {
                    self.statement(child, &mut update, 0);
                }
            }
            (vec![init, test, body, update], "for")
        } else if node.native_kind == "do_statement" {
            (vec![body, test], "do")
        } else {
            (vec![test, body], "while")
        };
        self.emit(
            region,
            node,
            "loop",
            vec![],
            false,
            &[],
            regions,
            json!({"form":form,"continue_region":if counted{"update"}else{"test"}}),
        );
    }
}
