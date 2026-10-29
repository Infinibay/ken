//! Virtual correspondence uses resolved signatures, never basename overload guesses.
use super::*;
use crate::{TypeRef, parse_type};
impl Project {
    fn signature_key(&self, reference: &TypeRef, context: &str) -> Option<Value> {
        if reference.kind == "nominal" {
            return self
                .resolve(&reference.native, context)
                .map(|id| json!(["nominal", id]));
        }
        if matches!(
            reference.kind.as_str(),
            "pointer" | "reference" | "rvalue_reference" | "qualified" | "array"
        ) {
            if reference.arguments.len() != 1 {
                return None;
            }
            let inner = self.signature_key(&reference.arguments[0], context)?;
            let mut qualifiers = reference.qualifiers.clone();
            qualifiers.sort();
            return Some(json!([reference.kind, qualifiers, reference.extent, inner]));
        }
        matches!(
            reference.kind.as_str(),
            "int" | "float" | "char" | "bool" | "void"
        )
        .then(|| json!([reference.kind, reference.native]))
    }
    pub(super) fn cpp_overrides(&mut self) {
        let methods = self
            .methods
            .iter()
            .map(|(key, methods)| (key.clone(), methods.clone()))
            .collect::<Vec<_>>();
        let cpp = methods
            .iter()
            .flat_map(|((owner, _), methods)| {
                methods
                    .iter()
                    .filter(|m| self.attr(m, "language") == "cpp")
                    .map(|m| (m.clone(), owner.clone()))
            })
            .collect::<BTreeMap<_, _>>();
        if cpp.is_empty() {
            return;
        }
        let mut parameters = BTreeMap::<String, Vec<(i64, String)>>::new();
        for f in self.rows("HAS_PARAMETER") {
            if !truth(&fact_attr(&f, "receiver")) {
                parameters
                    .entry(f.subject.clone())
                    .or_default()
                    .push((fact_attr(&f, "position").as_i64().unwrap_or(0), f.object));
            }
        }
        let mut signatures = BTreeMap::new();
        for method in cpp.keys() {
            let mut parts = Vec::new();
            let mut reason = "";
            if !self.flag(method, "cpp_signature_syntax") {
                reason = "unsupported-declarator";
            } else if self.flag(method, "static") || self.flag(method, "constructor") {
                reason = "non-instance-method";
            } else {
                let mut params = parameters.get(method).cloned().unwrap_or_default();
                params.sort();
                for (_, parameter) in params {
                    let mut reference = parse_type(
                        self.attr(&parameter, "native_type").as_str().unwrap_or(""),
                        "cpp",
                    );
                    if reference.kind == "array" {
                        reference.kind = "pointer".into();
                        reference.bits = None;
                        reference.signed = None;
                        reference.extent = None;
                        reference.rank = None;
                        reference.qualifiers.clear();
                    }
                    while reference.kind == "qualified" && !reference.arguments.is_empty() {
                        reference = reference.arguments.remove(0);
                    }
                    if let Some(key) = self.signature_key(&reference, &parameter) {
                        parts.push(key);
                    } else {
                        reason = "unresolved-parameter-type";
                        break;
                    }
                }
            }
            if reason.is_empty() {
                signatures.insert(
                    method.clone(),
                    json!([
                        self.entity(method).name,
                        parts,
                        self.attr(method, "cv_qualifiers"),
                        self.attr(method, "ref_qualifier"),
                        self.attr(method, "cpp_variadic")
                    ]),
                );
            }
            self.add(
                method,
                "METHOD_SIGNATURE_STATUS",
                if reason.is_empty() {
                    "supported"
                } else {
                    "unsupported"
                },
                "",
                json!({"analysis":"cpp-virtual-signatures/1","reason":reason}),
            );
        }
        let mut pairs = Vec::new();
        for ((owner, name), implementations) in &methods {
            if !implementations.iter().any(|m| signatures.contains_key(m)) {
                continue;
            }
            for base in self
                .ancestors(owner)
                .into_iter()
                .filter(|base| base != owner)
            {
                for implementation in implementations {
                    for original in self
                        .methods
                        .get(&(base.clone(), name.clone()))
                        .into_iter()
                        .flatten()
                    {
                        if signatures.contains_key(implementation)
                            && signatures.contains_key(original)
                            && signatures[implementation] == signatures[original]
                        {
                            pairs.push((implementation.clone(), original.clone()));
                        }
                    }
                }
            }
        }
        let mut virtuals = signatures
            .keys()
            .filter(|m| self.flag(m, "explicit_virtual"))
            .cloned()
            .collect::<BTreeSet<_>>();
        loop {
            let added = pairs
                .iter()
                .filter(|(implementation, original)| {
                    virtuals.contains(original) && !virtuals.contains(implementation)
                })
                .map(|(implementation, _)| implementation.clone())
                .collect::<BTreeSet<_>>();
            if added.is_empty() {
                break;
            }
            virtuals.extend(added);
        }
        for method in &virtuals {
            self.add(
                method,
                "VIRTUAL_METHOD",
                &cpp[method],
                "",
                json!({"basis":"cpp-resolved-virtual-signature"}),
            );
        }
        for (implementation, original) in pairs {
            if virtuals.contains(&original) {
                self.add(
                    &implementation,
                    "OVERRIDES",
                    &original,
                    &self.ev(&implementation),
                    json!({"basis":"cpp-resolved-virtual-signature"}),
                );
            }
        }
    }
}
