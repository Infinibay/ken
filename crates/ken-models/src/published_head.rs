//! Compile the one published CLS/Dense/exactGELU/LayerNorm/Dense recipe.
use crate::{ModelError, VerifiedSnapshot, onnx_wire as wire};
use safetensors::{Dtype, SafeTensors};
use serde_json::Value;

const PREFIX: &str = "ken_published_head/";
fn invalid(message: impl Into<String>) -> ModelError {
    ModelError::Weights(message.into())
}
fn config(source: &VerifiedSnapshot, name: &str) -> Result<Value, ModelError> {
    Ok(serde_json::from_slice(
        source.artifact(&format!("{name}/config.json"))?,
    )?)
}
fn weight(
    source: &VerifiedSnapshot,
    module: &str,
    name: &str,
    shape: &[usize],
) -> Result<Vec<u8>, ModelError> {
    let data = SafeTensors::deserialize(source.artifact(&format!("{module}/model.safetensors"))?)
        .map_err(|e| invalid(e.to_string()))?;
    let tensor = data.tensor(name).map_err(|e| invalid(e.to_string()))?;
    if tensor.dtype() != Dtype::F32
        || tensor.shape() != shape
        || tensor
            .data()
            .chunks_exact(4)
            .any(|bytes| !f32::from_le_bytes(bytes.try_into().expect("four bytes")).is_finite())
    {
        return Err(invalid("unsupported or nonfinite published head weights"));
    }
    Ok(tensor.data().to_vec())
}
fn transpose(data: &[u8], rows: usize, columns: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(data.len());
    for column in 0..columns {
        for row in 0..rows {
            let offset = (row * columns + column) * 4;
            out.extend_from_slice(&data[offset..offset + 4]);
        }
    }
    out
}
struct Head {
    nodes: Vec<Vec<u8>>,
    initializers: Vec<Vec<u8>>,
}
impl Head {
    fn constant(&mut self, name: &str, dtype: u64, dims: &[usize], data: &[u8]) -> String {
        let name = format!("{PREFIX}{name}");
        let mut tensor = Vec::new();
        for dim in dims {
            tensor.extend(wire::integer(1, *dim as u64));
        }
        tensor.extend(wire::integer(2, dtype));
        tensor.extend(wire::bytes(8, name.as_bytes()));
        tensor.extend(wire::bytes(9, data));
        self.initializers.push(wire::bytes(5, &tensor));
        name
    }
    fn node(&mut self, op: &str, inputs: &[&str], name: &str, attributes: Vec<Vec<u8>>) -> String {
        let name = format!("{PREFIX}{name}");
        let mut node = Vec::new();
        for input in inputs {
            node.extend(wire::bytes(1, input.as_bytes()));
        }
        node.extend(wire::bytes(2, name.as_bytes()));
        node.extend(wire::bytes(3, name.as_bytes()));
        node.extend(wire::bytes(4, op.as_bytes()));
        for attribute in attributes {
            node.extend(wire::bytes(5, &attribute));
        }
        self.nodes.push(wire::bytes(1, &node));
        name
    }
}
fn axis(value: i64) -> Vec<u8> {
    [
        wire::bytes(1, b"axis"),
        wire::integer(3, value as u64),
        wire::integer(20, 2),
    ]
    .concat()
}
fn epsilon() -> Vec<u8> {
    [
        wire::bytes(1, b"epsilon"),
        wire::float(2, 1e-5),
        wire::integer(20, 1),
    ]
    .concat()
}
fn output(name: &str) -> Vec<u8> {
    let shape = [
        wire::bytes(1, &wire::bytes(2, b"batch_size")),
        wire::bytes(1, &wire::integer(1, 1)),
    ]
    .concat();
    let tensor = [wire::integer(1, 1), wire::bytes(2, &shape)].concat();
    let value = [
        wire::bytes(1, name.as_bytes()),
        wire::bytes(2, &wire::bytes(1, &tensor)),
    ]
    .concat();
    wire::bytes(12, &value)
}
fn check_names(graph: &[wire::Field<'_>]) -> Result<(), ModelError> {
    for field in graph {
        let tags: &[u32] = match field.tag {
            1 => &[1, 2, 3],
            5 => &[8],
            11..=13 => &[1],
            _ => continue,
        };
        for name in wire::message(*field)?
            .into_iter()
            .filter(|f| tags.contains(&f.tag))
        {
            if wire::text(name)?.starts_with(PREFIX) {
                return Err(invalid("published head namespace collision"));
            }
        }
    }
    Ok(())
}

pub fn compile_head(source: &VerifiedSnapshot) -> Result<Vec<u8>, ModelError> {
    let pool = config(source, "1_Pooling")?;
    let dense = config(source, "2_Dense")?;
    let norm = config(source, "3_LayerNorm")?;
    let out = config(source, "4_Dense")?;
    let hidden = pool["embedding_dimension"]
        .as_u64()
        .and_then(|n| usize::try_from(n).ok())
        .filter(|n| *n > 0)
        .ok_or_else(|| invalid("positive published hidden dimension required"))?;
    if pool["pooling_mode"] != "cls"
        || dense["in_features"] != hidden
        || dense["out_features"] != hidden
        || dense["bias"] != false
        || dense["activation_function"] != "torch.nn.modules.activation.GELU"
        || norm["dimension"] != hidden
        || out["in_features"] != hidden
        || out["out_features"] != 1
        || out["bias"] != true
        || out["activation_function"] != "torch.nn.modules.linear.Identity"
    {
        return Err(invalid("unsupported published head architecture"));
    }
    let dense_weight = weight(source, "2_Dense", "linear.weight", &[hidden, hidden])?;
    let norm_weight = weight(source, "3_LayerNorm", "norm.weight", &[hidden])?;
    let norm_bias = weight(source, "3_LayerNorm", "norm.bias", &[hidden])?;
    let out_weight = weight(source, "4_Dense", "linear.weight", &[1, hidden])?;
    let out_bias = weight(source, "4_Dense", "linear.bias", &[1])?;
    let model = wire::fields(source.artifact("onnx/model.onnx")?)?;
    let opset = model
        .iter()
        .find(|f| f.tag == 8)
        .ok_or_else(|| invalid("published backbone opset missing"))?;
    if wire::number(wire::unique(&wire::message(*opset)?, 2)?)? != 18 {
        return Err(invalid("unsupported published backbone opset"));
    }
    let graph = wire::message(wire::unique(&model, 7)?)?;
    let token_output = wire::message(wire::unique(&graph, 12)?)?;
    let token_name = wire::text(wire::unique(&token_output, 1)?)?;
    if token_name.is_empty() {
        return Err(invalid("published output name required"));
    }
    check_names(&graph)?;
    let mut head = Head {
        nodes: Vec::new(),
        initializers: Vec::new(),
    };
    let cls_index = head.constant("cls_index", 7, &[], &0i64.to_le_bytes());
    let cls = head.node("Gather", &[token_name, &cls_index], "cls", vec![axis(1)]);
    let w = head.constant(
        "dense_weight",
        1,
        &[hidden, hidden],
        &transpose(&dense_weight, hidden, hidden),
    );
    let dense = head.node("MatMul", &[&cls, &w], "dense", vec![]);
    let sqrt2 = head.constant("sqrt2", 1, &[], &std::f32::consts::SQRT_2.to_le_bytes());
    let scaled = head.node("Div", &[&dense, &sqrt2], "scaled", vec![]);
    let erf = head.node("Erf", &[&scaled], "erf", vec![]);
    let one = head.constant("one", 1, &[], &1f32.to_le_bytes());
    let plus_one = head.node("Add", &[&erf, &one], "plus_one", vec![]);
    let product = head.node("Mul", &[&dense, &plus_one], "gelu_product", vec![]);
    let half = head.constant("half", 1, &[], &0.5f32.to_le_bytes());
    let gelu = head.node("Mul", &[&product, &half], "gelu", vec![]);
    let nw = head.constant("norm_weight", 1, &[hidden], &norm_weight);
    let nb = head.constant("norm_bias", 1, &[hidden], &norm_bias);
    let norm = head.node(
        "LayerNormalization",
        &[&gelu, &nw, &nb],
        "norm",
        vec![axis(-1), epsilon()],
    );
    let ow = head.constant(
        "out_weight",
        1,
        &[hidden, 1],
        &transpose(&out_weight, 1, hidden),
    );
    let scores = head.node("MatMul", &[&norm, &ow], "scores", vec![]);
    let ob = head.constant("out_bias", 1, &[1], &out_bias);
    let logits = head.node("Add", &[&scores, &ob], "logits", vec![]);
    let with_nodes = wire::append(&graph, 1, &head.nodes);
    let with_weights = wire::append(&wire::fields(&with_nodes)?, 5, &head.initializers);
    drop(with_nodes);
    let with_output = wire::replace(&wire::fields(&with_weights)?, 12, &[output(&logits)]);
    drop(with_weights);
    let graph_field = wire::bytes(7, &with_output);
    drop(with_output);
    Ok(wire::replace(&model, 7, &[graph_field]))
}
