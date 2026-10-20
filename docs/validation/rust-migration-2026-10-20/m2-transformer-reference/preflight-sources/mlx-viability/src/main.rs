//! Private exact-core MLX primitive experiment; no application implementation.
use mlx_rs::{Array,Dtype,memory};
use serde_json::json;
fn main()->Result<(),Box<dyn std::error::Error>>{
 let core_version=unsafe {let mut text=mlx_sys::mlx_string_new();assert_eq!(mlx_sys::mlx_version(&mut text),0);let value=std::ffi::CStr::from_ptr(mlx_sys::mlx_string_data(text)).to_str()?.to_owned();assert_eq!(mlx_sys::mlx_string_free(text),0);value};
 assert_eq!(core_version,"0.32.3");
 let mut cases=Vec::new();
 for dtype in [Dtype::Float32,Dtype::Float16,Dtype::Bfloat16]{
  let a={let mut input=vec![1_f32,2.,3.,4.];let a=Array::from_slice(&input,&[2,2]);input.fill(99.);a.as_dtype(dtype)?};
  let result=a.matmul(&a)?;result.eval()?;let floats=result.as_dtype(Dtype::Float32)?;let values=floats.as_slice::<f32>();assert_eq!(values,[7.,10.,15.,22.]);
  let bad=Array::from_slice(&[1_f32,2.,3.,4.],&[4,1]).as_dtype(dtype)?;let invalid=a.matmul(&bad).is_err();assert!(invalid);
  cases.push(json!({"dtype":format!("{dtype:?}"),"values":values,"invalid_shape_rejected":invalid,"owned_input":true}));
 }
 let host_limit=memory::memory_limit()?;let mut caps=Vec::new();
 for prior in [0,64*1024*1024,1024*1024*1024]{memory::set_cache_limit(prior)?;let old=memory::set_cache_limit(512*1024*1024)?;if old<512*1024*1024{memory::set_cache_limit(old)?;}let actual=memory::set_cache_limit(prior)?;assert_eq!(actual,prior.min(512*1024*1024));caps.push(json!({"previous":prior,"after_bound":actual}));}
 assert_eq!(memory::memory_limit()?,host_limit);
 println!("{}",json!({"format":"ken-mlx-native-primitive/1","cases":cases,"cache_limits":caps,"host_limit_unchanged":true,"native_core_version":core_version,"device":format!("{}",mlx_rs::Device::try_default()?),"model_inference_accepted":false}));Ok(())
}
