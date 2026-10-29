//! Source branch evidence separates truthiness, membership, tags and null polarity.
use super::*;
impl<'a, 's> Unit<'a, 's> {
    fn branch_arms(&mut self, node: SyntaxNode<'a>, id: &str, evidence: &str) {
        for (relation, field_name) in [
            ("BRANCH_TRUE", "consequence"),
            ("BRANCH_FALSE", "alternative"),
        ] {
            if let Some(body) = node.field(field_name) {
                let body = self.branch_region(body);
                self.add(
                    id,
                    relation,
                    &source::operation_id(&self.ir.path, body),
                    evidence,
                    json!({}),
                );
            }
        }
    }
    pub(super) fn condition_facts(&mut self, node: SyntaxNode<'a>, scope: &str, cls: &str) {
        let kind = node.kind();
        let ev = self.evidence(node);
        let oid = source::operation_id(&self.ir.path, node);
        if matches!(kind, "ternary_expression" | "conditional_expression") {
            let value = self.value(Some(node), scope, cls);
            self.add(&value, "SYNTAX_NODE", &oid, &ev, json!({}));
            for arm_name in ["consequence", "alternative"] {
                if let Some(arm) = node.field(arm_name) {
                    let value = self.value(Some(arm), scope, cls);
                    self.add(
                        &source::operation_id(&self.ir.path, arm),
                        "VALUE",
                        &value,
                        &ev,
                        json!({"basis":"conditional-arm-operand"}),
                    );
                }
            }
        }
        let Some(condition) = node.field("condition") else {
            return;
        };
        let mut tested = self.unwrap(condition);
        let mut positive = true;
        let mut operands = Vec::new();
        let mut operator = String::new();
        for _ in 0..32 {
            operands = tested
                .named_children()
                .into_iter()
                .filter(|n| !n.kind().contains("comment"))
                .collect();
            operator = tested
                .children()
                .into_iter()
                .filter(|n| !n.is_named())
                .map(|n| self.text(Some(n)))
                .collect::<Vec<_>>()
                .join(" ");
            if !matches!(
                tested.kind(),
                "not_operator" | "unary_expression" | "prefix_unary_expression"
            ) || !matches!(operator.as_str(), "not" | "!")
                || operands.len() != 1
            {
                break;
            }
            positive = !positive;
            tested = self.unwrap(operands[0]);
        }
        if vocabulary().calls.contains(tested.kind())
            || vocabulary().members.contains(tested.kind())
            || super::semantics::index_kind(tested.kind())
            || tested.kind() == "identifier"
        {
            let value = self.value(Some(tested), scope, cls);
            self.add(
                &oid,
                "TRUTH_TEST",
                &value,
                &ev,
                json!({"when":if positive{"true"}else{"false"},"basis":"condition-syntax"}),
            );
            self.branch_arms(node, &oid, &ev);
        } else if self.language == Language::Python
            && tested.kind() == "comparison_operator"
            && operands.len() == 2
            && matches!(operator.as_str(), "in" | "not in")
        {
            let key = self.value(Some(operands[0]), scope, cls);
            let container = self.value(Some(operands[1]), scope, cls);
            self.add(&oid,"MEMBERSHIP_CONTAINER",&container,&ev,json!({"when":if(operator=="in")==positive{"true"}else{"false"},"basis":"membership-syntax"}));
            self.add(
                &oid,
                "MEMBERSHIP_KEY",
                &key,
                &ev,
                json!({"basis":"membership-syntax"}),
            );
            self.branch_arms(node, &oid, &ev);
        } else if matches!(tested.kind(), "comparison_operator" | "binary_expression")
            && operands.len() == 2
            && matches!(
                operator.as_str(),
                "==" | "!=" | "===" | "!==" | "<" | ">" | "<=" | ">="
            )
        {
            let mut null = false;
            for &side in &operands {
                if self.value(Some(side), scope, cls) == "NULL" {
                    null = true;
                    break;
                }
            }
            if !null {
                for &side in &operands {
                    let value = self.value(Some(side), scope, cls);
                    if let Some(&position) = self.positions.get(&value) {
                        let kind = &self.ir.entities[position].1.kind;
                        if matches!(kind.as_str(), "STORAGE" | "MEMBER")
                            && matches!(operator.as_str(), "==" | "!=" | "===" | "!==")
                        {
                            self.add(
                                &oid,
                                "TRUTH_TEST",
                                &value,
                                &ev,
                                json!({"basis":"comparison-syntax"}),
                            );
                        } else if kind == "PARAMETER" {
                            self.add(
                                &oid,
                                "PARAMETER_TEST",
                                &value,
                                &ev,
                                json!({"basis":"comparison-syntax"}),
                            );
                        }
                    }
                }
                self.branch_arms(node, &oid, &ev);
            }
        }
        let operands = tested
            .named_children()
            .into_iter()
            .filter(|n| !n.kind().contains("comment"))
            .collect::<Vec<_>>();
        let operator = tested
            .children()
            .into_iter()
            .filter(|n| !n.is_named())
            .map(|n| self.text(Some(n)))
            .collect::<Vec<_>>()
            .join(" ");
        if matches!(tested.kind(), "comparison_operator" | "binary_expression")
            && operands.len() == 2
            && matches!(
                operator.as_str(),
                "is" | "is not" | "==" | "!=" | "===" | "!=="
            )
        {
            if matches!(self.language, Language::JavaScript | Language::TypeScript)
                && !self.undefined_shadowed
            {
                let undefined = operands
                    .iter()
                    .map(|n| {
                        n.kind() == "undefined"
                            || (n.kind() == "identifier" && self.text(Some(*n)) == "undefined")
                    })
                    .collect::<Vec<_>>();
                if undefined[0] != undefined[1] {
                    let value = self.value(Some(operands[usize::from(undefined[0])]), scope, cls);
                    self.add(&oid,"UNDEFINED_TEST",&value,&ev,json!({"when":if matches!(operator.as_str(),"=="|"===")==positive{"true"}else{"false"},"operator":operator,"basis":"unshadowed-undefined-syntax"}));
                    self.branch_arms(node, &oid, &ev);
                }
            }
            let left = self.value(Some(operands[0]), scope, cls);
            let right = self.value(Some(operands[1]), scope, cls);
            if (left == "NULL") != (right == "NULL") {
                let value = if left == "NULL" { right } else { left };
                self.add(&oid,"NULL_TEST",&value,&ev,json!({"when":if matches!(operator.as_str(),"is"|"=="|"===")==positive{"true"}else{"false"},"operator":operator,"negated":!positive}));
                self.branch_arms(node, &oid, &ev);
            }
        }
    }
}
