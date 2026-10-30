use super::{Lowering, Operand, Operation, Region, identifier, text, tokens, wrapper};
use serde_json::json;
impl Lowering<'_, '_> {
    pub(super) fn address(&mut self, node: &Operation, region: &mut Region) -> Operand {
        let children = self.children(node);
        if wrapper(node) && children.len() == 1 {
            return self.address(self.node(children[0]), region);
        }
        if identifier(node) {
            let name = if node.attrs.contains_key("text") {
                text(node, "text")
            } else {
                node.native_kind.clone()
            };
            return Operand::new("place", self.place(&name));
        }
        if node.kind == "MEMBER" {
            let receiver = self.field(
                node,
                &["object", "value", "expression", "argument", "operand"],
            );
            let member = self.field(node, &["attribute", "property", "field", "name"]);
            let implicit = self.function.language == "csharp" && tokens(node) == ["this", "."];
            if let Some(member) = member
                && (receiver.is_some() || implicit)
            {
                let base = if let Some(receiver) = receiver {
                    self.expression(self.node(receiver), region, 0)
                } else {
                    let place = self.place("this");
                    self.emit(
                        region,
                        node,
                        "slot.load",
                        vec![Operand::new("place", place)],
                        true,
                        &["read.binding"],
                        vec![],
                        json!({"implicit_receiver":true}),
                    )
                    .unwrap()
                };
                return self
                    .emit(
                        region,
                        node,
                        "field.addr",
                        vec![base],
                        true,
                        &[],
                        vec![],
                        json!({"field":text(self.node(member),"text")}),
                    )
                    .unwrap();
            }
        }
        if Self::indexed(node) {
            let (mut receiver, mut index) = (
                self.field(
                    node,
                    &[
                        "value",
                        "object",
                        "argument",
                        "array",
                        "expression",
                        "operand",
                    ],
                ),
                self.field(node, &["subscript", "index", "indices"]),
            );
            if self.function.language == "rust" && children.len() == 2 {
                receiver = Some(children[0]);
                index = Some(children[1]);
            }
            if let (Some(receiver), Some(index)) = (receiver, index) {
                let base = self.expression(self.node(receiver), region, 0);
                let offset = self.expression(self.node(index), region, 0);
                return self
                    .emit(
                        region,
                        node,
                        "index.addr",
                        vec![base, offset],
                        true,
                        &[],
                        vec![],
                        json!({}),
                    )
                    .unwrap();
            }
        }
        self.opaque(node, region, "unknown-address")
    }
    fn indexed(node: &Operation) -> bool {
        matches!(
            node.native_kind.as_str(),
            "subscript"
                | "subscript_expression"
                | "element_access_expression"
                | "index_expression"
                | "array_access"
        )
    }
    pub(super) fn expression(
        &mut self,
        node: &Operation,
        region: &mut Region,
        depth: usize,
    ) -> Operand {
        if self.active >= 64 {
            return self.opaque(node, region, "nesting-limit");
        }
        self.active += 1;
        let result = self.expression_inner(node, region, depth);
        self.active -= 1;
        result
    }
    fn expression_inner(&mut self, node: &Operation, region: &mut Region, depth: usize) -> Operand {
        if depth > 64 {
            return self.opaque(node, region, "nesting-limit");
        }
        if self.source.optional.contains(&node.id) {
            return self.opaque(node, region, "optional-evaluation");
        }
        let children = self.children(node);
        if wrapper(node) && children.len() == 1 {
            return self.expression(self.node(children[0]), region, depth + 1);
        }
        if identifier(node) {
            let place = self.address(node, region);
            return self
                .emit(
                    region,
                    node,
                    "slot.load",
                    vec![place],
                    true,
                    &["read.binding"],
                    vec![],
                    json!({}),
                )
                .unwrap();
        }
        if node.kind == "MEMBER" || Self::indexed(node) {
            let address = self.address(node, region);
            return self
                .emit(
                    region,
                    node,
                    "memory.load",
                    vec![address],
                    true,
                    &["read.memory", "unknown"],
                    vec![],
                    json!({"dispatch":"native"}),
                )
                .unwrap();
        }
        if matches!(
            node.native_kind.as_str(),
            "conditional_expression" | "ternary_expression"
        ) {
            let (mut condition, mut consequence, mut alternative) = (
                self.field(node, &["condition"]),
                self.field(node, &["consequence"]),
                self.field(node, &["alternative"]),
            );
            if self.function.language == "python" && children.len() == 3 {
                consequence = Some(children[0]);
                condition = Some(children[1]);
                alternative = Some(children[2]);
            }
            let (Some(condition), Some(consequence), Some(alternative)) =
                (condition, consequence, alternative)
            else {
                return self.opaque(node, region, "conditional-expression");
            };
            let value = self.expression(self.node(condition), region, depth + 1);
            let consequence = self.value_region(self.node(consequence), "consequence", depth + 1);
            let alternative = self.value_region(self.node(alternative), "alternative", depth + 1);
            return self
                .emit(
                    region,
                    node,
                    "choose",
                    vec![value],
                    true,
                    &["unknown"],
                    vec![consequence, alternative],
                    json!({"truth":"native","evaluation":"selected-arm-only"}),
                )
                .unwrap();
        }
        if matches!(node.kind.as_str(), "BINARY" | "UNARY" | "COMPARE") {
            let operators = self
                .source
                .operators
                .get(&node.id)
                .cloned()
                .unwrap_or_default();
            if self.function.language == "cpp" && matches!(node.kind.as_str(), "BINARY" | "COMPARE")
            {
                return self.opaque(node, region, "operator-evaluation-order");
            }
            if operators.len() == 1
                && matches!(operators[0].as_str(), "and" | "or" | "&&" | "||" | "??")
            {
                let (left, right) = (self.field(node, &["left"]), self.field(node, &["right"]));
                let (Some(left), Some(right)) = (left, right) else {
                    return self.opaque(node, region, "conditional-operator-dispatch");
                };
                if !matches!(
                    self.function.language.as_str(),
                    "python" | "javascript" | "typescript" | "java" | "go" | "rust"
                ) {
                    return self.opaque(node, region, "conditional-operator-dispatch");
                }
                let value = self.expression(self.node(left), region, depth + 1);
                let rhs = self.value_region(self.node(right), "rhs", depth + 1);
                return self.emit(region,node,"short_circuit",vec![value],true,&["unknown"],vec![rhs],json!({"operator":operators[0],"result_policy":if matches!(self.function.language.as_str(),"python"|"javascript"|"typescript"){"selected-operand"}else{"boolean"},"truth":if operators[0]=="??"{"nullish"}else{"native"}})).unwrap();
            }
            if operators.len() != 1 {
                return self.opaque(node, region, "conditional-or-chained-expression");
            }
            let mut operands = Vec::new();
            for index in children {
                let child = self.node(index);
                if child.role != "operator" {
                    operands.push(self.expression(child, region, depth + 1));
                }
            }
            return self
                .emit(
                    region,
                    node,
                    &node.kind.to_lowercase(),
                    operands,
                    true,
                    &["unknown"],
                    vec![],
                    json!({"operator":operators[0]}),
                )
                .unwrap();
        }
        if node.kind == "CALL" {
            return self.call(node, region, depth);
        }
        if matches!(node.kind.as_str(), "YIELD" | "AWAIT") {
            let delegated = node
                .attrs
                .get("delegated")
                .and_then(|v| serde_json::from_str::<bool>(v.get()).ok())
                .unwrap_or(false);
            let opcode = if node.kind == "YIELD" && delegated {
                "yield.delegate"
            } else if node.kind == "YIELD" {
                "yield"
            } else {
                "await"
            };
            let operands = children
                .into_iter()
                .map(|i| self.expression(self.node(i), region, depth + 1))
                .collect();
            return self
                .emit(
                    region,
                    node,
                    opcode,
                    operands,
                    true,
                    &["suspend", "unknown"],
                    vec![],
                    json!({}),
                )
                .unwrap();
        }
        if children.is_empty()
            && (node.native_kind.contains("literal")
                || matches!(
                    node.native_kind.as_str(),
                    "integer" | "float" | "number" | "true" | "false" | "none" | "null"
                ))
        {
            return self
                .emit(
                    region,
                    node,
                    "const",
                    vec![],
                    true,
                    &[],
                    vec![],
                    json!({"spelling":text(node,"text"),"native_kind":node.native_kind}),
                )
                .unwrap();
        }
        self.opaque(node, region, "expression-lowering")
    }
    fn call(&mut self, node: &Operation, region: &mut Region, depth: usize) -> Operand {
        let callee = self.field(node, &["function", "constructor", "type", "name"]);
        let arguments = self.field(node, &["arguments"]);
        let args = arguments
            .map(|i| self.children(self.node(i)))
            .unwrap_or_default();
        let Some(mut callee) = callee else {
            return self.opaque(node, region, "call-binding");
        };
        if args.iter().any(|&i| {
            matches!(
                self.node(i).native_kind.as_str(),
                "keyword_argument"
                    | "list_splat"
                    | "dictionary_splat"
                    | "spread_element"
                    | "named_argument"
            )
        }) {
            return self.opaque(node, region, "call-binding");
        }
        if self.function.language == "cpp" && args.len() > 1 {
            return self.opaque(node, region, "argument-evaluation-order");
        }
        let mut receiver = self.field(node, &["object"]);
        let member_call = self.node(callee).kind == "MEMBER" || receiver.is_some();
        let mut implicit_this = false;
        if self.node(callee).kind == "MEMBER" {
            implicit_this =
                self.function.language == "csharp" && tokens(self.node(callee)) == ["this", "."];
            receiver = self.field(
                self.node(callee),
                &["object", "value", "expression", "argument", "operand"],
            );
            let Some(member) = self.field(
                self.node(callee),
                &["attribute", "property", "field", "name"],
            ) else {
                return self.opaque(node, region, "member-call");
            };
            callee = member;
        }
        let mut values = receiver
            .map(|i| vec![self.expression(self.node(i), region, 0)])
            .unwrap_or_default();
        if implicit_this && values.is_empty() {
            let place = self.place("this");
            values.push(
                self.emit(
                    region,
                    node,
                    "slot.load",
                    vec![Operand::new("place", place)],
                    true,
                    &["read.binding"],
                    vec![],
                    json!({"implicit_receiver":true}),
                )
                .unwrap(),
            );
        }
        if let Some(first) = values.first_mut() {
            first.role = "receiver".into();
        }
        let bound = self
            .source
            .symbols
            .get(&self.entity.id)
            .is_some_and(|s| s.contains_key(&text(self.node(callee), "text")));
        if !member_call && bound && self.function.language != "java" {
            let mut value = self.expression(self.node(callee), region, 0);
            value.role = "callee".into();
            values.push(value);
        } else if self.node(callee).attrs.contains_key("text") {
            let mut value = Operand::new("symbol", text(self.node(callee), "text"));
            value.role = "callee".into();
            values.push(value);
        } else {
            values.push(self.expression(self.node(callee), region, 0));
        }
        for (position, index) in args.into_iter().enumerate() {
            let mut value = self.expression(self.node(index), region, depth + 1);
            value.role = format!("argument:{position}");
            values.push(value);
        }
        let code = if matches!(
            node.native_kind.as_str(),
            "new_expression" | "object_creation_expression"
        ) {
            "construct"
        } else {
            "call"
        };
        self.emit(
            region,
            node,
            code,
            values,
            true,
            &["invoke", "unknown"],
            vec![],
            json!({}),
        )
        .unwrap()
    }
}
