//! Python3.12 body observations over immutable catalog snapshots.
mod admission;
mod ast;
mod expression;
use crate::{
    EntityKey,
    source_catalog::SourceCatalog,
    source_snapshot::{SourceResult, invalid},
};
use ruff_python_ast::{
    self as py, Expr, Stmt,
    visitor::{self, Visitor},
};
use std::{
    collections::{BTreeSet, HashMap},
    sync::Arc,
};
pub struct PythonOperationWitnesses {
    catalog: Arc<SourceCatalog>,
    files: HashMap<String, Option<ast::PythonFile>>,
    owners: HashMap<EntityKey, BTreeSet<String>>,
}
impl PythonOperationWitnesses {
    pub fn new(catalog: Arc<SourceCatalog>) -> Self {
        Self {
            catalog,
            files: HashMap::new(),
            owners: HashMap::new(),
        }
    }
    pub fn supports(path: &str) -> bool {
        path.ends_with(".py") || path.ends_with(".pyi")
    }
    pub fn for_owner(&mut self, key: &EntityKey) -> SourceResult<BTreeSet<String>> {
        self.catalog.passages(key)?;
        if !Self::supports(&key.path) {
            return Err(invalid("Python witness backend requires .py or .pyi"));
        }
        if let Some(value) = self.owners.get(key) {
            return Ok(value.clone());
        }
        let file = self.files.entry(key.path.clone()).or_insert_with(|| {
            ast::PythonFile::parse(self.catalog.snapshots()[&key.path].lines().join("\n"))
        });
        let mut result = BTreeSet::new();
        if let Some(file) = file
            && let Some(body) = file.body(
                key.qualname
                    .as_deref()
                    .unwrap_or("")
                    .rsplit('.')
                    .next()
                    .unwrap_or(""),
                self.catalog.extent(key)?,
            )
        {
            let mut observer = BodyObserver {
                source: &file.source,
                result: &mut result,
            };
            observer.visit_body(body);
        }
        self.owners.insert(key.clone(), result.clone());
        Ok(result)
    }
}
struct BodyObserver<'a> {
    source: &'a str,
    result: &'a mut BTreeSet<String>,
}
impl<'a> Visitor<'a> for BodyObserver<'_> {
    fn visit_body(&mut self, body: &'a [Stmt]) {
        if snapshot_write(body, self.source) {
            self.result.insert("snapshot_keyed_write".into());
        }
        visitor::walk_body(self, body);
    }
    fn visit_stmt(&mut self, stmt: &'a Stmt) {
        match stmt {
            Stmt::FunctionDef(_) | Stmt::ClassDef(_) => return,
            Stmt::Raise(node)
                if node
                    .cause
                    .as_deref()
                    .is_some_and(|cause| !matches!(cause, Expr::NoneLiteral(_))) =>
            {
                let family = match node.exc.as_deref() {
                    Some(Expr::Call(call)) => match call.func.as_ref() {
                        Expr::Name(name) => name.id.as_str(),
                        _ => "unknown",
                    },
                    _ => "unknown",
                };
                self.result.insert(format!("cause:{family}"));
            }
            Stmt::Return(node) => {
                if let Some(Expr::BoolOp(value)) = node.value.as_deref()
                    && value.op == py::BoolOp::Or
                    && value.values.len() == 2
                    && let (Expr::Name(left), Expr::Named(right)) =
                        (&value.values[0], &value.values[1])
                    && matches!(right.target.as_ref(),Expr::Name(target)if target.id==left.id)
                    && matches!(right.value.as_ref(), Expr::Call(_))
                {
                    self.result.insert("returned_flag_refresh".into());
                }
            }
            _ => {}
        }
        visitor::walk_stmt(self, stmt);
    }
    fn visit_expr(&mut self, expr: &'a Expr) {
        if matches!(expr, Expr::Lambda(_)) {
            return;
        }
        if matches!(expr, Expr::Call(_)) {
            self.result.insert("invocation".into());
        }
        visitor::walk_expr(self, expr);
    }
}
fn snapshot_write(body: &[Stmt], source: &str) -> bool {
    for triple in body.windows(3) {
        let (Stmt::Assign(read), Stmt::Assign(write), Stmt::Expr(record)) =
            (&triple[0], &triple[1], &triple[2])
        else {
            continue;
        };
        let ([Expr::Name(old)], [Expr::Subscript(target)]) =
            (read.targets.as_slice(), write.targets.as_slice())
        else {
            continue;
        };
        let (Expr::Call(get), Expr::Call(append)) = (read.value.as_ref(), record.value.as_ref())
        else {
            continue;
        };
        let (Expr::Attribute(get_attr), Expr::Attribute(append_attr)) =
            (get.func.as_ref(), append.func.as_ref())
        else {
            continue;
        };
        let Some(key) = get.arguments.args.first() else {
            continue;
        };
        if get_attr.attr.as_str() != "get"
            || append_attr.attr.as_str() != "append"
            || append.arguments.args.len() != 1
        {
            continue;
        }
        let values = match &append.arguments.args[0] {
            Expr::Tuple(t) => &t.elts,
            Expr::List(l) => &l.elts,
            _ => continue,
        };
        if let [a, b, Expr::Name(prior)] = values.as_slice()
            && old.id == prior.id
            && expression::same(&target.value, &get_attr.value, source)
            && expression::same(&target.slice, key, source)
            && expression::same(a, &target.value, source)
            && expression::same(b, &target.slice, source)
        {
            return true;
        }
    }
    false
}
