//! Public advertising metadata and native registrations are independent facts.
//! The immutable original table is captured without preparing any model; native
//! dimensions/artifacts/acceptance continue to come from ModelCatalog alone.
use crate::Result;
use ken_models::{EncoderFamily, ModelDescriptor};
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn public_backend(family: EncoderFamily) -> &'static str {
    match family {
        EncoderFamily::FastEmbed => "fastembed",
        EncoderFamily::SentenceTransformer => "torch",
        EncoderFamily::StaticTable => "static_table",
        EncoderFamily::Potion => "potion",
        EncoderFamily::Mlx => "mlx",
    }
}
fn native(row: ModelDescriptor) -> Result<Value> {
    let backend = public_backend(row.backend);
    let mut value = serde_json::to_value(&row)?;
    value["native_backend"] = value["backend"].clone();
    value["backend"] = json!(backend);
    value["registered"] = json!(true);
    Ok(value)
}
pub(super) fn compose(
    default: String,
    legacy: &str,
    descriptors: Vec<ModelDescriptor>,
) -> Result<Value> {
    let metadata: Value = serde_json::from_str(include_str!("public-model-metadata.json"))?;
    let mut registered = descriptors
        .into_iter()
        .map(|row| (row.model.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let mut rows = vec![];
    let mut unsupported = vec![];
    for original in metadata["models"]
        .as_array()
        .expect("authenticated immutable public metadata rows")
    {
        let name = original["model"].as_str().expect("immutable model name");
        let mut row = if let Some(descriptor) = registered.remove(name) {
            native(descriptor)?
        } else {
            unsupported.push(name.to_owned());
            json!({"registered":false,"registration":null,"bytes":null,"native_backend":null,"native_inference_accepted":false})
        };
        // These are advertised original fields, not estimates from artifact
        // bytes, a native backend spelling or a heuristic on extension names.
        for field in ["model", "dim", "mb", "multilingual", "backend"] {
            row[field] = original[field].clone();
        }
        row["metadata_source"] = json!("original_public_catalogue");
        rows.push(row);
    }
    let mut additional = registered.into_values().collect::<Vec<_>>();
    additional.sort_by(|a, b| {
        a.dim
            .unwrap_or(0)
            .cmp(&b.dim.unwrap_or(0))
            .then(a.bytes.cmp(&b.bytes))
            .then(a.model.cmp(&b.model))
    });
    for descriptor in additional {
        let mut row = native(descriptor)?;
        row["mb"] = Value::Null;
        row["multilingual"] = Value::Null;
        row["metadata_source"] = json!("native_registration");
        rows.push(row);
    }
    Ok(json!({"default":default,"legacy":legacy,"models":rows,"unsupported_models":unsupported}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metadata_only_rows_are_explicitly_unregistered_and_never_claim_inference() {
        let result = compose("custom/default".into(), "legacy", vec![]).unwrap();
        let missing = result["unsupported_models"].as_array().unwrap();
        assert_eq!(missing.len(), 32);
        assert!(missing.iter().any(|v| v == "BAAI/bge-base-en"));
        for row in result["models"].as_array().unwrap() {
            assert_eq!(row["registered"], false);
            assert_eq!(row["native_inference_accepted"], false);
            assert!(row["registration"].is_null());
            assert!(row["native_backend"].is_null());
            assert!(row["dim"].is_number());
            assert!(row["mb"].is_number());
            assert!(row["multilingual"].is_boolean());
        }
    }
}
