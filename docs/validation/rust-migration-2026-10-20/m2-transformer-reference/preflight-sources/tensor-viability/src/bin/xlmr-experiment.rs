//! Temporary CPU XLM-R architecture experiment, not a migrated application backend.
use std::{collections::BTreeMap,fs,path::Path};
use serde_json::{Value,json};
use tch::{Device,Kind,Tensor};
type Result<T>=std::result::Result<T,Box<dyn std::error::Error>>;
fn linear(x:&Tensor,w:&BTreeMap<String,Tensor>,p:&str)->Tensor{x.linear(&w[&format!("{p}.weight")],Some(&w[&format!("{p}.bias")]))}
fn norm(x:&Tensor,w:&BTreeMap<String,Tensor>,p:&str,eps:f64)->Tensor{x.layer_norm([x.size()[2]],Some(&w[&format!("{p}.weight")]),Some(&w[&format!("{p}.bias")]),eps,true)}
fn infer(c:&Value,w:&BTreeMap<String,Tensor>,ids:&[Vec<i64>],masks:&[Vec<i64>])->Result<(Tensor,Tensor)>{
 let device=w["embeddings.word_embeddings.weight"].device();
 let n=ids.len() as i64;let s=ids[0].len() as i64;let hidden=c["hidden_size"].as_i64().ok_or("hidden")?;let heads=c["num_attention_heads"].as_i64().ok_or("heads")?;let eps=c["layer_norm_eps"].as_f64().ok_or("eps")?;
 let ids=Tensor::f_from_slice(&ids.iter().flatten().copied().collect::<Vec<_>>())?.to_device(device).reshape([n,s]);
 let pad=c["pad_token_id"].as_i64().ok_or("pad")?;let unpadded=ids.ne(pad).to_kind(Kind::Int64);let positions=unpadded.cumsum(1,Kind::Int64)*&unpadded+pad;
 let words=w["embeddings.word_embeddings.weight"].index_select(0,&ids.reshape([-1])).reshape([n,s,hidden]);
 let positions=w["embeddings.position_embeddings.weight"].index_select(0,&positions.reshape([-1])).reshape([n,s,hidden]);
 let mut x=&words+w["embeddings.token_type_embeddings.weight"].get(0).reshape([1,1,hidden]);x=&x+positions;x=norm(&x,w,"embeddings.LayerNorm",eps);
 let has_padding=masks.iter().flatten().any(|value|*value==0);
 let mask=Tensor::f_from_slice(&masks.iter().flatten().copied().collect::<Vec<_>>())?.to_kind(Kind::Bool).to_device(device).reshape([n,1,1,s]).expand([n,1,s,s],true);
 for layer in 0..c["num_hidden_layers"].as_i64().ok_or("layers")? {
  let p=format!("encoder.layer.{layer}");let query=linear(&x,w,&format!("{p}.attention.self.query")).reshape([n,s,heads,hidden/heads]).transpose(1,2);
  let key=linear(&x,w,&format!("{p}.attention.self.key")).reshape([n,s,heads,hidden/heads]).transpose(1,2);
  let value=linear(&x,w,&format!("{p}.attention.self.value")).reshape([n,s,heads,hidden/heads]).transpose(1,2);
  let attention=Tensor::f_scaled_dot_product_attention(&query,&key,&value,has_padding.then_some(&mask),0.0,false,None,false)?.transpose(1,2).reshape([n,s,hidden]);
  x=norm(&(linear(&attention,w,&format!("{p}.attention.output.dense"))+&x),w,&format!("{p}.attention.output.LayerNorm"),eps);
  let inner=linear(&x,w,&format!("{p}.intermediate.dense")).gelu("none");
  x=norm(&(linear(&inner,w,&format!("{p}.output.dense"))+&x),w,&format!("{p}.output.LayerNorm"),eps);
 }
 let mut pooled=x.select(1,0);
 for _ in 0..2{let length=pooled.norm_scalaropt_dim(2.0,[-1_i64],true).clamp_min(1e-12);pooled=&pooled/length;}
 let pooled=pooled.to_kind(Kind::Float);let vectors=&pooled/pooled.norm_scalaropt_dim(2.0,[-1_i64],true).clamp_min(1e-12);
 Ok((x,vectors))
}
fn main()->Result<()>{
 tch::set_num_threads(2);tch::set_num_interop_threads(1);let _guard=tch::no_grad_guard();
 let args:Vec<_>=std::env::args_os().collect();if args.len()!=3{return Err("usage: xlmr-experiment SNAPSHOT REQUESTS".into());}
 let source=Path::new(&args[1]);let config:Value=serde_json::from_slice(&fs::read(source.join("config.json"))?)?;
 assert_eq!(config["model_type"],"xlm-roberta");assert_eq!(config["position_embedding_type"],"absolute");assert_eq!(config["type_vocab_size"],1);
 let requests:Value=serde_json::from_slice(&fs::read(&args[2])?)?;let mut outputs=Vec::new();
 for case in requests["cases"].as_array().ok_or("cases")?{
  let kind=match case["dtype"].as_str(){Some("float32")=>Kind::Float,Some("float16")=>Kind::Half,Some("bfloat16")=>Kind::BFloat16,_=>return Err("unsupported dtype".into())};
  let device=match case["device"].as_str(){None|Some("cpu")=>Device::Cpu,Some("mps")=>Device::Mps,_=>return Err("unknown device".into())};
  if device==Device::Mps{assert!(tch::utils::has_mps());
   #[cfg(target_os="macos")] {unsafe extern "C"{fn ken_mps_cap_experiment(fraction:f64,error:*mut std::ffi::c_char,length:usize)->std::ffi::c_int;}
   let mut error=[0_i8;1024];let status=unsafe{ken_mps_cap_experiment(0.7,error.as_mut_ptr(),error.len())};if status!=0{return Err(unsafe{std::ffi::CStr::from_ptr(error.as_ptr())}.to_string_lossy().into_owned().into());}}
  }
  let weights:BTreeMap<_,_>=Tensor::loadz_multi_with_device(source.join("pytorch_model.bin"),Device::Cpu)?.into_iter().map(|(k,v)|(k,v.to_kind(kind).to_device(device))).collect();
  let ids:Vec<Vec<i64>>=serde_json::from_value(case["input_ids"].clone())?;let masks:Vec<Vec<i64>>=serde_json::from_value(case["attention_mask"].clone())?;
  let (hidden,vectors)=infer(&config,&weights,&ids,&masks)?;let (repeated,_)=infer(&config,&weights,&ids,&masks)?;
  outputs.push(json!({"dtype":case["dtype"],"device":format!("{device:?}"),"hidden_shape":hidden.size(),"hidden_f32":if case["include_hidden"]==false {None}else{Some(Vec::<f32>::try_from(&hidden.to_kind(Kind::Float).to_device(Device::Cpu).reshape([-1]))?)},"vectors_f32":Vec::<f32>::try_from(&vectors.to_device(Device::Cpu).reshape([-1]))?,"repeat_exact":hidden.equal(&repeated)}));
 }
 println!("{}",json!({"format":"ken-xlmr-native-viability/1","cases":outputs,"model_inference_accepted":false}));Ok(())
}
