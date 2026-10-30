use super::*;
use crate::relational::{OrderedMap, RelationalQuery};
use std::{collections::BTreeSet, sync::Arc};
struct Parser {
    tokens: Tokens,
    serial: usize,
    depth: usize,
}
fn selector(tag: &str) -> Option<&'static str> {
    Some(match tag {
        "entity" => "_",
        "type_decl" => "CLASS|INTERFACE",
        "class" => "CLASS",
        "interface" => "INTERFACE",
        "callable" | "method" | "function" | "closure" => "CALLABLE",
        "parameter" => "PARAMETER",
        "variable" => "STORAGE",
        "value" => "VALUE",
        "call" => "CALL",
        "module" => "MODULE",
        "resource" => "RESOURCE",
        "context" => "CONTEXT",
        _ => return None,
    })
}
fn nested(tag: &str) -> Option<(&'static str, &'static str)> {
    Some(match tag {
        "has_method" => ("HAS_METHOD", "CALLABLE"),
        "has_parameter" => ("HAS_PARAMETER", "PARAMETER"),
        "has_argument" => ("ARGUMENT", "ARGUMENT"),
        "has_field" => ("HAS_FIELD", "STORAGE"),
        _ => return None,
    })
}
impl Parser {
    fn value(&mut self) -> Result<(String, String)> {
        crate::with_stack(|| {
            self.depth += 1;
            if self.depth > 128 {
                return Err(invalid("legacy query nesting limit exceeded"));
            }
            let result = self.value_inner();
            self.depth -= 1;
            result
        })
    }
    fn value_inner(&mut self) -> Result<(String, String)> {
        let t = self.tokens.next()?;
        if t == "[" {
            let mut items = vec![];
            while !self.tokens.peek("]") {
                let (op, item) = self.value()?;
                if op != "=" {
                    return Err(invalid("alternatives require literals"));
                }
                items.push(item);
                if !self.tokens.peek("]") {
                    self.tokens.expect(",")?;
                }
            }
            self.tokens.expect("]")?;
            if items.is_empty() {
                return Err(invalid("empty alternatives"));
            }
            return Ok(("=".into(), items.join("|")));
        }
        if t.starts_with('"') {
            return serde_json::from_str(&t)
                .map(|v| ("=".into(), v))
                .map_err(|e| invalid(e.to_string()));
        }
        if let Some(raw) = t.strip_prefix('/') {
            let (pattern, flags) = raw.rsplit_once('/').unwrap();
            let mut previous = false;
            let mut backref = false;
            for c in pattern.chars() {
                if previous && matches!(c, '1'..='9') {
                    backref = true;
                }
                previous = c == '\\';
            }
            if pattern.chars().count() > 512 || backref || pattern.contains("(?") {
                return Err(invalid(
                    "KenQL regex must be regular: no backreferences or lookaround",
                ));
            }
            crate::execution::regex_runtime::Pattern::compile(
                pattern,
                flags,
                crate::execution::regex_runtime::Dialect::Regex,
                &mut || Ok(()),
            )?;
            return Ok((
                "regex".into(),
                if flags.is_empty() {
                    pattern.into()
                } else {
                    format!("(?{flags}){pattern}")
                },
            ));
        }
        Ok(("=".into(), t))
    }
    fn attrs(&mut self, end: &str) -> Result<Vec<(String, String, String)>> {
        let mut attrs = vec![];
        while !self.tokens.peek(end) {
            let key = self.tokens.next()?;
            self.tokens.expect(":")?;
            let (op, value) = self.value()?;
            if value != "*" {
                attrs.push((key, op, value));
            }
            if !self.tokens.peek(end) {
                self.tokens.expect(",")?;
            }
        }
        self.tokens.expect(end)?;
        Ok(attrs)
    }
    fn block(&mut self) -> Result<Vec<RelationalNode>> {
        crate::with_stack(|| {
            self.depth += 1;
            if self.depth > 128 {
                return Err(invalid("legacy query nesting limit exceeded"));
            }
            self.tokens.expect("{")?;
            let mut nodes = vec![];
            while !self.tokens.peek("}") {
                nodes.extend(self.statement("")?);
            }
            self.tokens.expect("}")?;
            self.depth -= 1;
            Ok(nodes)
        })
    }
    fn statement(&mut self, parent: &str) -> Result<Vec<RelationalNode>> {
        crate::with_stack(|| {
            let tag = self.tokens.next()?;
            if selector(&tag).is_some() || tag == "operation" || nested(&tag).is_some() {
                self.tokens.expect("(")?;
                let mut attrs = self.attrs(")")?;
                let alias = if self.tokens.peek("as") {
                    self.tokens.next()?;
                    self.tokens.variable()?
                } else {
                    self.serial += 1;
                    format!("$_local{}", self.serial)
                };
                const ALLOWED: &str = "instance_constructor visibility_basis visibility_status explicit_arguments name kind native_kind language type type_family type_state return_type return_family return_type_state position pos receiver parameter_kind declared static async generator visibility owner delegated method mutable storage_kind path path_glob resolution dispatch keyword spread_kind reference_kind native_type native_return_type constructor context_manager arity execution";
                let unknown: BTreeSet<_> = attrs
                    .iter()
                    .map(|(k, _, _)| k)
                    .filter(|k| {
                        !(ALLOWED.split_whitespace().any(|a| a == k.as_str())
                            || tag == "operation" && *k == "role")
                    })
                    .collect();
                if !unknown.is_empty() {
                    return Err(invalid(format!(
                        "unknown selector attributes: [{}]",
                        unknown.iter().map(|k| py(k)).collect::<Vec<_>>().join(", ")
                    )));
                }
                for (k, _, _) in &mut attrs {
                    if k == "pos" {
                        *k = "position".into();
                    }
                }
                if matches!(tag.as_str(), "method" | "function") {
                    attrs.push((
                        "method".into(),
                        "=".into(),
                        if tag == "method" { "true" } else { "false" }.into(),
                    ));
                }
                let mut nodes = vec![];
                let kind = if let Some((relation, kind)) = nested(&tag) {
                    if parent.is_empty() {
                        return Err(invalid(format!("{tag} requires an enclosing selector")));
                    }
                    nodes.push(edge(
                        Term::Text(parent.into()),
                        relation,
                        Term::Text(alias.clone()),
                        vec![],
                    ));
                    if tag == "has_parameter" && !attrs.iter().any(|(k, _, _)| k == "receiver") {
                        attrs.push(("receiver".into(), "=".into(), "false".into()));
                    }
                    kind
                } else {
                    if !parent.is_empty() {
                        return Err(invalid("nested selectors must name a relationship"));
                    }
                    selector(&tag).unwrap_or("_")
                };
                nodes.push(edge(
                    Term::Text(alias.clone()),
                    if tag == "operation" {
                        "OPERATION"
                    } else {
                        "ENTITY"
                    },
                    Term::Text(kind.into()),
                    attrs,
                ));
                if self.tokens.peek("{") {
                    self.tokens.next()?;
                    self.depth += 1;
                    if self.depth > 128 {
                        return Err(invalid("legacy query nesting limit exceeded"));
                    }
                    while !self.tokens.peek("}") {
                        nodes.extend(self.statement(&alias)?);
                    }
                    self.tokens.expect("}")?;
                    self.depth -= 1;
                } else {
                    self.tokens.expect(";")?;
                }
                return Ok(nodes);
            }
            let n = match tag.as_str() {
                "require" => {
                    let a = term(self.tokens.next()?)?;
                    let r = self.tokens.next()?;
                    let b = term(self.tokens.next()?)?;
                    if !r.starts_with(|c: char| c.is_ascii_uppercase())
                        || !r
                            .chars()
                            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
                    {
                        return Err(invalid("invalid relation"));
                    }
                    let attrs = if self.tokens.peek("[") {
                        self.tokens.next()?;
                        self.attrs("]")?
                    } else {
                        vec![]
                    };
                    self.tokens.expect(";")?;
                    edge(a, &r, b, attrs)
                }
                "match" => {
                    let name = self.tokens.next()?;
                    if !name.starts_with('"') {
                        return Err(invalid("match requires a quoted query id"));
                    }
                    let name: String =
                        serde_json::from_str(&name).map_err(|e| invalid(e.to_string()))?;
                    self.tokens.expect("(")?;
                    let mut bindings = OrderedMap::default();
                    while !self.tokens.peek(")") {
                        let role = self.tokens.next()?;
                        self.tokens.expect(":")?;
                        if bindings.get(&role).is_some() {
                            return Err(invalid(format!("duplicate role {role}")));
                        }
                        bindings.insert(role, text(self.tokens.variable()?));
                        if !self.tokens.peek(")") {
                            self.tokens.expect(",")?;
                        }
                    }
                    self.tokens.expect(")")?;
                    let proof = if self.tokens.peek("as") {
                        self.tokens.next()?;
                        self.tokens.variable()?
                    } else {
                        String::new()
                    };
                    self.tokens.expect(";")?;
                    node(
                        "match",
                        PlanValue::Tuple(vec![text(name), PlanValue::Map(bindings), text(proof)]),
                        vec![],
                    )
                }
                "any" => {
                    let mut branches = vec![self.block()?];
                    while self.tokens.peek("or") {
                        self.tokens.next()?;
                        branches.push(self.block()?);
                    }
                    if branches.len() < 2 {
                        return Err(invalid("any requires or"));
                    }
                    node("any", PlanValue::None, branches)
                }
                "optional" => node("optional", PlanValue::None, vec![self.block()?]),
                "not" => {
                    self.tokens.expect("exists")?;
                    let child = self.block()?;
                    self.tokens.expect("within")?;
                    let scope = self.tokens.next()?;
                    self.tokens.expect("(")?;
                    let owner = self.tokens.variable()?;
                    self.tokens.expect(")")?;
                    self.tokens.expect(";")?;
                    if !matches!(scope.as_str(), "callable" | "module") {
                        return Err(invalid("unsupported absence scope"));
                    }
                    node(
                        "not",
                        PlanValue::Tuple(vec![text(scope), text(owner)]),
                        vec![child],
                    )
                }
                "count" => {
                    self.tokens.expect("distinct")?;
                    let role = self.tokens.variable()?;
                    let op = self.tokens.next()?;
                    let number = self.tokens.next()?;
                    if number.is_empty() || !number.bytes().all(|c| c.is_ascii_digit()) {
                        return Err(invalid(format!(
                            "invalid literal for int() with base 10: {}",
                            py(&number)
                        )));
                    }
                    if !matches!(op.as_str(), ">=" | "<=" | "=" | ">" | "<") {
                        return Err(invalid("invalid count comparison"));
                    }
                    let child = self.block()?;
                    self.tokens.expect(";")?;
                    node(
                        "count",
                        PlanValue::Tuple(vec![
                            text(role),
                            text(op),
                            PlanValue::Integer(crate::IntegerLiteral::from_digits(&number)),
                        ]),
                        vec![child],
                    )
                }
                "where" => {
                    let a = self.tokens.next()?;
                    let op = self.tokens.next()?;
                    let b = self.tokens.next()?;
                    if !matches!(op.as_str(), "==" | "!=" | "<" | ">" | "<=" | ">=") {
                        return Err(invalid("invalid where comparison"));
                    }
                    self.tokens.expect(";")?;
                    node(
                        "where",
                        PlanValue::Tuple(vec![text(a), text(op), text(b)]),
                        vec![],
                    )
                }
                "different" => {
                    let a = self.tokens.variable()?;
                    let b = self.tokens.variable()?;
                    self.tokens.expect(";")?;
                    node(
                        "different",
                        PlanValue::Tuple(vec![text(a), text(b)]),
                        vec![],
                    )
                }
                "path" => {
                    let a = term(self.tokens.next()?)?;
                    let relation = self.tokens.next()?;
                    self.tokens.expect("{")?;
                    let lo = self.tokens.next()?;
                    self.tokens.expect(",")?;
                    let hi = self.tokens.next()?;
                    self.tokens.expect("}")?;
                    let b = term(self.tokens.next()?)?;
                    self.tokens.expect("as")?;
                    let proof = self.tokens.variable()?;
                    self.tokens.expect(";")?;
                    let range = lo.parse::<u32>().ok().zip(hi.parse::<u32>().ok());
                    if range.is_none_or(|(a, b)| a > b || b > 32) {
                        return Err(invalid("path bounds must satisfy 0 <= min <= max <= 32"));
                    }
                    node(
                        "path",
                        PlanValue::Tuple(vec![
                            PlanValue::Term(a),
                            text(relation),
                            PlanValue::Term(b),
                            PlanValue::Integer(crate::IntegerLiteral::from_digits(&lo)),
                            PlanValue::Integer(crate::IntegerLiteral::from_digits(&hi)),
                            text(proof),
                        ]),
                        vec![],
                    )
                }
                "emit" => {
                    let mut exports = OrderedMap::default();
                    loop {
                        let role = self.tokens.next()?;
                        let (name, variable) = if let Some(name) = role.strip_prefix('$') {
                            (name.into(), role)
                        } else {
                            self.tokens.expect("=")?;
                            (role, self.tokens.variable()?)
                        };
                        if exports.get(&name).is_some() {
                            return Err(invalid(format!("duplicate export {name}")));
                        }
                        exports.insert(name, text(variable));
                        if !self.tokens.peek(",") {
                            break;
                        }
                        self.tokens.next()?;
                    }
                    self.tokens.expect(";")?;
                    node("emit", PlanValue::Map(exports), vec![])
                }
                _ => return Err(invalid(format!("unknown KenQL clause {tag}"))),
            };
            Ok(vec![n])
        })
    }
}
fn raw(v: &PlanValue) -> &str {
    if let PlanValue::Term(t) = v {
        t.token()
    } else {
        ""
    }
}
fn tuple(v: &PlanValue) -> &[PlanValue] {
    if let PlanValue::Tuple(v) = v { v } else { &[] }
}
fn bound(nodes: &[RelationalNode], initial: &BTreeSet<String>) -> Result<BTreeSet<String>> {
    crate::with_stack(|| {
        let mut bound = initial.clone();
        for n in nodes {
            let values = tuple(&n.value);
            match n.kind.as_str() {
                "fact" => {
                    if let PlanValue::Edge(e) = &n.value {
                        for t in [&e.subject, &e.object] {
                            if t.token().starts_with('$') {
                                bound.insert(t.token().into());
                            }
                        }
                    }
                }
                "match" => {
                    if let PlanValue::Map(m) = &values[1] {
                        bound.extend(m.items().iter().map(|(_, v)| raw(v).into()));
                    }
                }
                "path" => {
                    for i in [0, 2, 5] {
                        let t = raw(&values[i]);
                        if t.starts_with('$') {
                            bound.insert(t.into());
                        }
                    }
                }
                "any" => {
                    let mut branches = n.children.iter().map(|b| self::bound(b, &bound));
                    let mut common = branches.next().transpose()?.unwrap_or_default();
                    for b in branches {
                        let b = b?;
                        common.retain(|r| b.contains(r));
                    }
                    bound.extend(common);
                }
                "optional" | "not" | "count" => {
                    let local = self::bound(&n.children[0], &bound)?;
                    if n.kind == "count" && !local.contains(raw(&values[0])) {
                        return Err(invalid("unbound count role"));
                    }
                    if n.kind == "not" && !bound.contains(raw(&values[1])) {
                        return Err(invalid("unbound absence scope"));
                    }
                }
                "where" => {
                    for i in [0, 2] {
                        let role = raw(&values[i]).split('.').next().unwrap();
                        if role.starts_with('$') && !bound.contains(role) {
                            return Err(invalid("where requires bound roles"));
                        }
                    }
                }
                "different" if values.iter().any(|v| !bound.contains(raw(v))) => {
                    return Err(invalid("different requires bound roles"));
                }
                "emit" => return Err(invalid("nested emit is not allowed")),
                _ => (),
            }
        }
        Ok(bound)
    })
}
pub fn parse(source: &str) -> Result<RelationalQuery> {
    let mut p = Parser {
        tokens: Tokens::new(source, Grammar::Blocks)?,
        serial: 0,
        depth: 0,
    };
    p.tokens.expect("query")?;
    let name = p.tokens.next()?;
    let mut nodes = p.block()?;
    if p.tokens.at != p.tokens.tokens.len() {
        return Err(invalid("unexpected tokens after query"));
    }
    if nodes.last().is_none_or(|n| n.kind != "emit") {
        return Err(invalid("query must end with emit"));
    }
    let emit = nodes.pop().unwrap();
    if nodes.iter().any(|n| n.kind == "emit") {
        return Err(invalid("emit must be last"));
    }
    let PlanValue::Map(map) = emit.value else {
        unreachable!()
    };
    let exports: OrderedMap<_> = map
        .items()
        .iter()
        .map(|(k, v)| (k.clone(), raw(v).into()))
        .collect();
    let bound = bound(&nodes, &BTreeSet::new())?;
    if exports
        .items()
        .iter()
        .any(|(_, role)| !bound.contains(role))
    {
        return Err(invalid("emit requires positively bound roles"));
    }
    Ok(RelationalQuery {
        name,
        nodes: Arc::new(nodes),
        exports,
        definitions: Default::default(),
    })
}
