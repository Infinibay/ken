//! Immutable request-local ranking observations with score and order replay.
use crate::{
    EntityKey, Result, RetrievalError,
    matrix::Matrix,
    number_json,
    numeric_ranker::NumericRanker,
    query::{Candidate, CodeMatch},
};
use ken_text::PythonText;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read, sync::Arc};
pub const MODEL_ORDER_POLICY: &str = "exact_priority_then_model_score_then_proposal_order";
pub const EXACT_ORDER_POLICY: &str = "unique_exact";
pub struct TraceObservation<'a> {
    pub model: &'a Arc<NumericRanker>,
    pub query: &'a PythonText,
    pub expanded: &'a PythonText,
    pub candidates: &'a [Candidate],
    pub matches: &'a [CodeMatch],
    pub values: Option<&'a Matrix<f64>>,
    pub feature_version: usize,
    pub evidence_version: usize,
    pub policy: &'a str,
    pub piece_kind: Option<&'a str>,
}
pub struct RankingTrace {
    request_id: String,
    attempt: u64,
    data: Option<Value>,
    model: Option<Arc<NumericRanker>>,
    values: Option<Matrix<f64>>,
    index: BTreeMap<EntityKey, usize>,
    query: Option<PythonText>,
    expanded: Option<PythonText>,
}
fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn query_hash(text: &PythonText) -> Result<String> {
    let text = text
        .to_utf8()
        .ok_or_else(|| invalid("ranking trace query is not scalar Unicode"))?;
    Ok(format!("{:x}", Sha256::digest(text.as_bytes())))
}
fn number(value: &Value) -> Result<f64> {
    number_json::read(value).ok_or_else(|| invalid("ranking trace requires numeric values"))
}
fn exact(owner: &Value) -> Result<f64> {
    owner["signals"].get("exact").map(number).unwrap_or(Ok(0.))
}
fn entity(owner: &Value) -> Result<EntityKey> {
    let mut key = owner["entity"]
        .as_object()
        .ok_or_else(|| invalid("ranking trace owner is invalid"))?
        .clone();
    key.insert("path".into(), owner["path"].clone());
    Ok(serde_json::from_value(Value::Object(key))?)
}
impl RankingTrace {
    pub fn new(request_id: Option<String>) -> Result<Self> {
        let request_id = match request_id.filter(|s| !s.is_empty()) {
            Some(id) => id,
            None => {
                let mut bytes = [0u8; 16];
                std::fs::File::open("/dev/urandom")
                    .and_then(|mut f| f.read_exact(&mut bytes))
                    .map_err(|e| invalid(&format!("request identity entropy: {e}")))?;
                bytes[6] = (bytes[6] & 15) | 64;
                bytes[8] = (bytes[8] & 63) | 128;
                let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
                format!(
                    "{}-{}-{}-{}-{}",
                    &hex[..8],
                    &hex[8..12],
                    &hex[12..16],
                    &hex[16..20],
                    &hex[20..]
                )
            }
        };
        Ok(Self {
            request_id,
            attempt: 0,
            data: None,
            model: None,
            values: None,
            index: BTreeMap::new(),
            query: None,
            expanded: None,
        })
    }
    pub fn request_id(&self) -> &str {
        &self.request_id
    }
    pub fn record(&mut self, observation: TraceObservation<'_>) -> Result<()> {
        let o = observation;
        if o.values.is_some_and(|v| {
            v.rows() != o.candidates.len() || v.columns() != o.model.features().len()
        }) {
            return Err(invalid("ranking trace feature shape mismatch"));
        }
        let ranked: BTreeMap<_, _> = o
            .matches
            .iter()
            .enumerate()
            .map(|(i, m)| (&m.entity, (i + 1, m)))
            .collect();
        let mut owners = Vec::with_capacity(o.candidates.len());
        for (i, c) in o.candidates.iter().enumerate() {
            let (rank, m) = ranked
                .get(&c.entity)
                .ok_or_else(|| invalid("ranking trace has no match for a proposed owner"))?;
            let values = o.values.map(|v| {
                v.values()[i * v.columns()..(i + 1) * v.columns()]
                    .iter()
                    .map(|n| number_json::value(*n))
                    .collect::<Vec<_>>()
            });
            let signals: BTreeMap<_, _> = c
                .signals
                .iter()
                .map(|(k, v)| (k, number_json::value(*v)))
                .collect();
            owners.push(json!({"path":c.entity.path,"entity":{"kind":c.entity.kind,"qualname":c.entity.qualname,"owner":c.entity.owner,"definition_ordinal":c.entity.definition_ordinal},"proposal_index":i,"rank":rank,"score":number_json::value(m.score),"source_hash":m.source_hash,"signals":signals,"feature_values":values}));
        }
        let attempt = self
            .attempt
            .checked_add(1)
            .ok_or_else(|| invalid("ranking trace attempt overflow"))?;
        let data = json!({"schema":1,"request_id":self.request_id,"attempt":attempt,"entry_point":"retrieval.owner_ranking","model_fingerprint":o.model.fingerprint()?,"feature_version":o.feature_version,"evidence_version":o.evidence_version,"requested_piece_kind":o.piece_kind,"policy":o.policy,"feature_names":o.model.features(),"owners":owners,"query_sha256":query_hash(o.query)?,"expanded_query_sha256":query_hash(o.expanded)?});
        self.attempt = attempt;
        self.data = Some(data);
        self.query = Some(o.query.clone());
        self.expanded = Some(o.expanded.clone());
        self.model = o.values.map(|_| o.model.clone());
        self.values = o.values.cloned();
        self.index = o
            .candidates
            .iter()
            .enumerate()
            .map(|(i, c)| (c.entity.clone(), i))
            .collect();
        Ok(())
    }
    pub fn to_json(&self, include_query: bool) -> Result<String> {
        let mut data = self
            .data
            .clone()
            .ok_or_else(|| invalid("ranking trace has no observation"))?;
        if include_query {
            if let Some(q) = &self.query {
                data["query"] = serde_json::to_value(q)?;
            }
            if let Some(q) = &self.expanded {
                data["expanded_query"] = serde_json::to_value(q)?;
            }
        }
        Ok(serde_json::to_string(&data)?)
    }
    pub fn from_json(raw: &str, model: &NumericRanker) -> Result<Self> {
        let data: Value = serde_json::from_str(raw)?;
        if data["schema"] != json!(1)
            || data["model_fingerprint"] != model.fingerprint()?
            || data["feature_names"] != serde_json::to_value(model.features())?
        {
            return Err(invalid("ranking trace model or feature schema mismatch"));
        }
        let owners = data["owners"]
            .as_array()
            .ok_or_else(|| invalid("ranking trace owners are invalid"))?;
        let mut ranks: Vec<_> = owners.iter().map(|o| o["rank"].as_u64()).collect();
        ranks.sort();
        if owners
            .iter()
            .enumerate()
            .any(|(i, o)| o["proposal_index"].as_u64() != Some(i as u64))
            || ranks != (1..=owners.len() as u64).map(Some).collect::<Vec<_>>()
        {
            return Err(invalid("ranking trace proposal/final order is invalid"));
        }
        let index: BTreeMap<_, _> = owners
            .iter()
            .enumerate()
            .map(|(i, o)| Ok((entity(o)?, i)))
            .collect::<Result<_>>()?;
        if index.len() != owners.len() {
            return Err(invalid("ranking trace contains duplicate owners"));
        }
        let values = if data["policy"] == EXACT_ORDER_POLICY {
            if owners.len() != 1
                || exact(&owners[0])? == 0.
                || !owners[0]["feature_values"].is_null()
            {
                return Err(invalid("ranking trace exact bypass is invalid"));
            }
            None
        } else {
            if data["policy"] != MODEL_ORDER_POLICY {
                return Err(invalid("unknown ranking trace order policy"));
            }
            let mut flat = Vec::new();
            for owner in owners {
                flat.extend(
                    owner["feature_values"]
                        .as_array()
                        .ok_or_else(|| invalid("ranking trace feature values are invalid"))?
                        .iter()
                        .map(number)
                        .collect::<Result<Vec<_>>>()?,
                );
            }
            let values = Matrix::new(owners.len(), model.features().len(), flat)?;
            let scores = model.predict(&values)?;
            let recorded: Vec<_> = owners
                .iter()
                .map(|o| number(&o["score"]))
                .collect::<Result<_>>()?;
            if scores != recorded {
                return Err(invalid("ranking trace scores do not reproduce"));
            }
            let priorities: Vec<_> = owners.iter().map(exact).collect::<Result<_>>()?;
            let mut order: Vec<_> = (0..owners.len()).collect();
            order.sort_by(|a, b| {
                priorities[*b]
                    .partial_cmp(&priorities[*a])
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| {
                        scores[*b]
                            .partial_cmp(&scores[*a])
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
            });
            if order
                .iter()
                .enumerate()
                .any(|(rank, i)| owners[*i]["rank"].as_u64() != Some(rank as u64 + 1))
            {
                return Err(invalid("ranking trace final order does not reproduce"));
            }
            Some(values)
        };
        let request_id = data["request_id"]
            .as_str()
            .ok_or_else(|| invalid("ranking trace request identity is invalid"))?;
        let mut result = Self::new(Some(request_id.into()))?;
        result.attempt = data["attempt"]
            .as_u64()
            .ok_or_else(|| invalid("ranking trace attempt is invalid"))?;
        let mut retained = serde_json::Map::new();
        for field in [
            "schema",
            "request_id",
            "attempt",
            "entry_point",
            "model_fingerprint",
            "feature_version",
            "evidence_version",
            "policy",
            "feature_names",
            "owners",
            "query_sha256",
            "expanded_query_sha256",
        ] {
            retained.insert(
                field.into(),
                data.get(field)
                    .ok_or_else(|| invalid("ranking trace field is missing"))?
                    .clone(),
            );
        }
        if let Some(kind) = data.get("requested_piece_kind") {
            retained.insert("requested_piece_kind".into(), kind.clone());
        }
        for (field, pin, slot) in [
            ("query", "query_sha256", &mut result.query),
            (
                "expanded_query",
                "expanded_query_sha256",
                &mut result.expanded,
            ),
        ] {
            if let Some(q) = data.get(field) {
                let q: PythonText = serde_json::from_value(q.clone())?;
                if query_hash(&q)? != data[pin] {
                    return Err(invalid("ranking trace query hash does not match"));
                }
                *slot = Some(q);
            }
        }
        result.model = values.as_ref().map(|_| Arc::new(model.clone()));
        result.values = values;
        result.index = index;
        result.data = Some(Value::Object(retained));
        Ok(result)
    }
    pub fn compare(&self, left: &EntityKey, right: &EntityKey) -> Result<Value> {
        let (data, model, values) = match (&self.data, &self.model, &self.values) {
            (Some(d), Some(m), Some(v)) => (d, m, v),
            _ => {
                return Err(invalid(
                    "no numeric feature observation is available for comparison",
                ));
            }
        };
        let position = |key: &EntityKey| {
            self.index
                .get(key)
                .copied()
                .ok_or_else(|| invalid("ranking trace owner is not present"))
        };
        let (i, j) = (position(left)?, position(right)?);
        let (a, b) = (&data["owners"][i], &data["owners"][j]);
        let reason = if exact(a)? != exact(b)? {
            "exact_identity_priority"
        } else if number(&a["score"])? != number(&b["score"])? {
            "numeric_model_score"
        } else {
            "stable_proposal_order"
        };
        let row = |i: usize| &values.values()[i * values.columns()..(i + 1) * values.columns()];
        let (x, y) = (row(i), row(j));
        let differing:Vec<_>=model.features().iter().zip(x).zip(y).filter(|((_,x),y)|x!=y).map(|((name,x),y)|json!({"feature":name,"left":number_json::value(*x),"right":number_json::value(*y)})).collect();
        Ok(
            json!({"request_id":self.request_id,"ordering_reason":reason,"left":a,"right":b,"differing_features":differing,"numeric":model.explain_pair(x,y)?}),
        )
    }
}
