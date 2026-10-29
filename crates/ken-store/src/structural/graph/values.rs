//! Schema15 native values. The database is the bounded deduplication dictionary.
use super::{Result, StructuralError};
use ken_program::value::{GraphValue as V, float_hex, parse_float_hex};
use ken_text::PythonText;
use rusqlite::{Connection, OptionalExtension, params};
use sha2::{Digest, Sha256};
pub struct GraphValues<'a> {
    pub(crate) db: &'a Connection,
    pub(crate) graph: i64,
}
impl<'a> GraphValues<'a> {
    pub fn new(db: &'a Connection, graph: i64) -> Self {
        Self { db, graph }
    }
    pub fn term(&self, text: &str) -> Result<i64> {
        if let Some(id) = self.lookup(text)? {
            return Ok(id);
        }
        let id: i64 = self.db.query_row(
            "SELECT coalesce(max(term_id),0)+1 FROM k2_graph_terms WHERE graph_id=?1",
            [self.graph],
            |r| r.get(0),
        )?;
        self.db.execute(
            "INSERT INTO k2_graph_terms VALUES(?1,?2,?3)",
            params![self.graph, id, text],
        )?;
        Ok(id)
    }
    pub fn lookup(&self, text: &str) -> Result<Option<i64>> {
        Ok(self
            .db
            .query_row(
                "SELECT term_id FROM k2_graph_terms WHERE graph_id=?1 AND text=?2",
                params![self.graph, text],
                |r| r.get(0),
            )
            .optional()?)
    }
    pub fn word(&self, id: i64) -> Result<String> {
        Ok(self.db.query_row(
            "SELECT text FROM k2_graph_terms WHERE graph_id=?1 AND term_id=?2",
            params![self.graph, id],
            |r| r.get(0),
        )?)
    }
    pub fn put(&self, value: &V) -> Result<i64> {
        self.put_depth(value, 0)
    }
    fn put_depth(&self, v: &V, depth: usize) -> Result<i64> {
        if depth > 512 {
            return Err(StructuralError::Invalid(
                "graph value nesting limit exceeded",
            ));
        }
        let mut children = Vec::new();
        let mut text: Option<String> = None;
        let mut integer: Option<i64> = None;
        let mut real: Option<f64> = None;
        let identity = match v {
            V::Dict(items) => {
                for (k, v) in items {
                    let key = k.to_utf8().ok_or(StructuralError::Invalid(
                        "SQLite text cannot contain isolated surrogates",
                    ))?;
                    let child = self.put_depth(v, depth + 1)?;
                    children.push((Some(key), child, v.comparison()));
                }
                V::Tuple(
                    children
                        .iter()
                        .map(|(k, id, _)| {
                            V::Tuple(vec![
                                V::String(k.as_deref().unwrap().into()),
                                V::Int(id.to_string()),
                            ])
                        })
                        .collect(),
                )
            }
            V::List(items) | V::Tuple(items) | V::Set(items) => {
                let mut items: Vec<_> = items.iter().collect();
                if matches!(v, V::Set(_)) {
                    items.sort_by_cached_key(|v| v.repr());
                }
                for v in items {
                    children.push((None, self.put_depth(v, depth + 1)?, v.comparison()));
                }
                V::Tuple(
                    children
                        .iter()
                        .map(|(_, id, _)| V::Int(id.to_string()))
                        .collect(),
                )
            }
            V::Null => V::Null,
            V::Bool(b) => {
                integer = Some(i64::from(*b));
                V::Int(integer.unwrap().to_string())
            }
            V::Int(n) => {
                let digits = n.strip_prefix('-').unwrap_or(n);
                if digits.is_empty()
                    || !digits.bytes().all(|b| b.is_ascii_digit())
                    || (digits.len() > 1 && digits.starts_with('0'))
                    || n == "-0"
                {
                    return Err(StructuralError::Invalid("noncanonical graph integer"));
                }
                integer = n.parse().ok();
                if integer.is_none() {
                    text = Some(n.clone());
                }
                v.clone()
            }
            V::Float(f) => {
                let hex = float_hex(*f);
                if f.is_finite() && hex != "-0x0.0p+0" {
                    real = Some(*f);
                } else {
                    text = Some(hex.clone());
                }
                V::String(hex.into())
            }
            V::String(s) => {
                text = Some(s.to_utf8().ok_or(StructuralError::Invalid(
                    "SQLite text cannot contain isolated surrogates",
                ))?);
                v.clone()
            }
        };
        let repr = V::Tuple(vec![V::String(v.tag().into()), identity]).repr();
        let signature = Sha256::digest(repr.as_bytes()).to_vec();
        if let Some(id) = self
            .db
            .query_row(
                "SELECT value_id FROM k2_graph_values WHERE graph_id=?1 AND signature=?2",
                params![self.graph, signature],
                |r| r.get(0),
            )
            .optional()?
        {
            return Ok(id);
        }
        let id: i64 = self.db.query_row(
            "SELECT coalesce(max(value_id),0)+1 FROM k2_graph_values WHERE graph_id=?1",
            [self.graph],
            |r| r.get(0),
        )?;
        self.db.execute(
            "INSERT INTO k2_graph_values VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![
                self.graph,
                id,
                signature,
                self.term(v.tag())?,
                text,
                integer,
                real
            ],
        )?;
        for (i, (key, child, comparison)) in children.into_iter().enumerate() {
            self.db.execute(
                "INSERT INTO k2_graph_members VALUES(?1,?2,?3,?4,?5,?6)",
                params![
                    self.graph,
                    id,
                    i as i64,
                    key.as_deref().map(|k| self.term(k)).transpose()?,
                    child,
                    self.term(&comparison)?
                ],
            )?;
        }
        Ok(id)
    }
    pub fn get(&self, id: i64) -> Result<V> {
        self.get_depth(id, 0)
    }
    fn get_depth(&self, id: i64, depth: usize) -> Result<V> {
        if depth > 512 {
            return Err(StructuralError::Invalid(
                "cyclic or excessively nested graph value",
            ));
        }
        if id < 0 {
            return self.operation_attributes(id, depth);
        }
        let (tag,text,integer,real):(i64,Option<String>,Option<i64>,Option<f64>)=self.db.query_row("SELECT tag,text_value,integer_value,real_value FROM k2_graph_values WHERE graph_id=?1 AND value_id=?2",params![self.graph,id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?;
        let tag = self.word(tag)?;
        Ok(match tag.as_str() {
            "NoneType" => V::Null,
            "bool" => V::Bool(integer.ok_or(StructuralError::Invalid("invalid bool column"))? != 0),
            "int" => V::Int(
                integer
                    .map(|i| i.to_string())
                    .or(text)
                    .ok_or(StructuralError::Invalid("invalid integer column"))?,
            ),
            "str" => V::String(
                text.ok_or(StructuralError::Invalid("invalid text column"))?
                    .into(),
            ),
            "float" => V::Float(if let Some(v) = real {
                v
            } else {
                parse_float_hex(
                    text.as_deref()
                        .ok_or(StructuralError::Invalid("invalid float column"))?,
                )?
            }),
            "dict" | "list" | "tuple" | "set" => {
                let mut stmt=self.db.prepare("SELECT key,child FROM k2_graph_members WHERE graph_id=?1 AND parent=?2 ORDER BY ordinal")?;
                let mut rows = stmt.query(params![self.graph, id])?;
                let mut items = Vec::new();
                let mut dict = Vec::new();
                while let Some(row) = rows.next()? {
                    let key: Option<i64> = row.get(0)?;
                    let child = self.get_depth(row.get(1)?, depth + 1)?;
                    if tag == "dict" {
                        dict.push((
                            PythonText::from(self.word(
                                key.ok_or(StructuralError::Invalid("missing dictionary key"))?,
                            )?),
                            child,
                        ));
                    } else {
                        items.push(child);
                    }
                }
                match tag.as_str() {
                    "dict" => V::Dict(dict),
                    "list" => V::List(items),
                    "tuple" => V::Tuple(items),
                    _ => V::Set(items),
                }
            }
            _ => return Err(StructuralError::Invalid("unknown graph value tag")),
        })
    }
    /// Decode just one dictionary member, leaving unrelated subtrees on disk.
    pub fn member(&self, id: i64, key: &str) -> Result<Option<V>> {
        if id < 0 {
            let column = match key {
                "kind" => Some("a.kind"),
                "native_kind" => Some("o.native_kind"),
                "owner" => Some("o.owner"),
                "role" => Some("o.role"),
                "start_byte" => Some("o.start_byte"),
                "end_byte" => Some("o.end_byte"),
                _ => None,
            };
            if let Some(column) = column {
                let n:i64=self.db.query_row(&format!("SELECT {column} FROM k2_graph_operation_attributes a JOIN k2_graph_operations o ON o.graph_id=a.graph_id AND o.ordinal=a.operation_ordinal WHERE a.graph_id=?1 AND a.fact_ordinal=?2"),params![self.graph,-(id+1)],|r|r.get(0))?;
                return Ok(Some(if matches!(key, "start_byte" | "end_byte") {
                    V::Int(n.to_string())
                } else {
                    V::String(self.word(n)?.into())
                }));
            }
            let residual:i64=self.db.query_row("SELECT residual FROM k2_graph_operation_attributes WHERE graph_id=?1 AND fact_ordinal=?2",params![self.graph,-(id+1)],|r|r.get(0))?;
            return self.member(residual, key);
        }
        let Some(key) = self.lookup(key)? else {
            return Ok(None);
        };
        let child: Option<i64> = self
            .db
            .query_row(
                "SELECT child FROM k2_graph_members WHERE graph_id=?1 AND parent=?2 AND key=?3",
                params![self.graph, id, key],
                |r| r.get(0),
            )
            .optional()?;
        child.map(|i| self.get(i)).transpose()
    }
    fn operation_attributes(&self, id: i64, depth: usize) -> Result<V> {
        let (kind,native,owner,role,start,end,residual):(i64,i64,i64,i64,i64,i64,i64)=self.db.query_row("SELECT a.kind,o.native_kind,o.owner,o.role,o.start_byte,o.end_byte,a.residual FROM k2_graph_operation_attributes a JOIN k2_graph_operations o ON o.graph_id=a.graph_id AND o.ordinal=a.operation_ordinal WHERE a.graph_id=?1 AND a.fact_ordinal=?2",params![self.graph,-(id+1)],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?)))?;
        let V::Dict(mut attrs) = self.get_depth(residual, depth + 1)? else {
            return Err(StructuralError::Invalid("invalid operation attributes"));
        };
        for (k, id) in [
            ("kind", kind),
            ("native_kind", native),
            ("owner", owner),
            ("role", role),
        ] {
            attrs.push((k.into(), V::String(self.word(id)?.into())));
        }
        attrs.push(("start_byte".into(), V::Int(start.to_string())));
        attrs.push(("end_byte".into(), V::Int(end.to_string())));
        Ok(V::Dict(attrs))
    }
}
