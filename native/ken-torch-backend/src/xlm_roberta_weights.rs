//! XLM-R parameter shapes and its declared, unused base-model pooler.
use crate::{CoreError, invalid, weights, xlm_roberta::XlmRobertaConfig};
use ken_native_model_api::{TransformerDevice, TransformerDtype};
use std::{collections::BTreeMap, path::Path};
use tch::{Device, Kind, Tensor};

pub struct XlmRobertaWeights {
    pub(crate) config: XlmRobertaConfig,
    tensors: BTreeMap<String, Tensor>,
    pub(crate) device: Device,
    pub(crate) kind: Kind,
}

impl XlmRobertaWeights {
    pub fn load(
        config: &XlmRobertaConfig,
        path: &Path,
        device: TransformerDevice,
        dtype: TransformerDtype,
    ) -> Result<Self, CoreError> {
        config.validate()?;
        let expected = expected(config);
        let maximum = expected
            .values()
            .try_fold(0_u64, |total, shape| {
                let elements = shape
                    .iter()
                    .try_fold(1_u64, |n, &size| n.checked_mul(size as u64))?;
                total.checked_add(elements.checked_mul(4)?)
            })
            .and_then(|n| n.checked_add(ken_native_model_api::MAX_PAYLOAD as u64))
            .ok_or_else(|| invalid("XLM-R storage size overflow"))?;
        let items = weights::read_parameter_zip(path, maximum, expected.len())?;
        let device = weights::resolve_device(device)?;
        let kind = weights::resolve_kind(dtype);
        let tensors = weights::owned_tensors(items, expected, config.layout, device, kind)?;
        Ok(Self {
            config: config.clone(),
            tensors,
            device,
            kind,
        })
    }
    pub(crate) fn get(&self, name: &str) -> Result<&Tensor, CoreError> {
        self.tensors
            .get(name)
            .ok_or_else(|| invalid(format!("missing owned XLM-R weight: {name}")))
    }
}

fn expected(c: &XlmRobertaConfig) -> BTreeMap<String, Vec<i64>> {
    let h = c.hidden_size;
    let mut result = BTreeMap::from([
        (
            "embeddings.word_embeddings.weight".into(),
            vec![c.vocab_size, h],
        ),
        (
            "embeddings.position_embeddings.weight".into(),
            vec![c.max_position_embeddings as i64, h],
        ),
        (
            "embeddings.token_type_embeddings.weight".into(),
            vec![c.type_vocab_size, h],
        ),
        ("embeddings.LayerNorm.weight".into(), vec![h]),
        ("embeddings.LayerNorm.bias".into(), vec![h]),
        // The registered XLMRobertaModel has a pooler although ST uses hidden states.
        ("pooler.dense.weight".into(), vec![h, h]),
        ("pooler.dense.bias".into(), vec![h]),
    ]);
    for layer in 0..c.num_hidden_layers {
        let p = format!("encoder.layer.{layer}");
        for (name, rows, columns) in [
            ("attention.self.query", h, h),
            ("attention.self.key", h, h),
            ("attention.self.value", h, h),
            ("attention.output.dense", h, h),
            ("intermediate.dense", c.intermediate_size, h),
            ("output.dense", h, c.intermediate_size),
        ] {
            result.insert(format!("{p}.{name}.weight"), vec![rows, columns]);
            result.insert(format!("{p}.{name}.bias"), vec![rows]);
        }
        for name in ["attention.output.LayerNorm", "output.LayerNorm"] {
            result.insert(format!("{p}.{name}.weight"), vec![h]);
            result.insert(format!("{p}.{name}.bias"), vec![h]);
        }
    }
    result
}
