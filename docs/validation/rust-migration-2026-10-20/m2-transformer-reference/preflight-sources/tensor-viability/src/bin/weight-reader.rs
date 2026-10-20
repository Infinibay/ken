//! Isolated native PyTorch archive reader experiment, not an application feature.
use serde_json::json;
use tch::{Device,Tensor};
fn main()->Result<(),Box<dyn std::error::Error>>{
 let path=std::env::args_os().nth(1).ok_or("usage: weight-reader FILE")?;
 let tensors=Tensor::loadz_multi_with_device(path,Device::Cpu)?;
 let inventory:Vec<_>=tensors.iter().map(|(name,value)|json!({"name":name,"shape":value.size(),"kind":format!("{:?}",value.kind()),"device":format!("{:?}",value.device())})).collect();
 println!("{}",json!({"format":"ken-native-torch-archive-exploration/1","tensors":inventory,"model_inference_accepted":false}));Ok(())
}
