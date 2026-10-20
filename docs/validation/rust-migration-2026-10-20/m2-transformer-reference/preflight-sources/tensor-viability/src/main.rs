//! Isolated library experiment, not a migrated model or application adapter.
//! APIs verified against the checksum-pinned published tch0.22.0 sources.
use serde_json::json;
use tch::{Device, Kind, Tensor};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let tensor = {
        let mut input = vec![1_f32, 2., 3., 4.];
        let owned = Tensor::f_from_slice(&input)?.f_reshape([2, 2])?;
        input.fill(99.);
        owned
    };
    let mut cases = Vec::new();
    for kind in [Kind::Float, Kind::Double, Kind::BFloat16] {
        let value = tensor.f_to_kind(kind)?;
        let result = value.f_matmul(&value)?;
        assert_eq!(result.device(), Device::Cpu);
        assert_eq!(result.kind(), kind);
        assert_eq!(result.size(), [2, 2]);
        let values: Vec<f32> = Vec::try_from(&result.f_reshape([-1])?)?;
        assert_eq!(values, [7., 10., 15., 22.]);
        let invalid = value.f_matmul(&value.f_reshape([4, 1])?).is_err();
        assert!(invalid);
        cases.push(json!({"dtype":format!("{kind:?}"),"device":"cpu", "shape":result.size(),
            "values":values,"invalid_shape_rejected":invalid,"input_mutation_did_not_change_tensor":true}));
    }
    println!("{}", json!({"format":"ken-libtorch-primitive-native/1","binding":"tch0.22.0",
        "pinned_core":"2.9.0","cases":cases,"model_inference_accepted":false}));
    Ok(())
}
