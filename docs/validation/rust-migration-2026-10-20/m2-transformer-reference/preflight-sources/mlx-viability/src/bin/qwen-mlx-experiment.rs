//! Private MLX Qwen architecture viability; not an accepted application backend.
use std::{collections::BTreeMap,fs,path::Path};
use serde_json::{Value,json};
use mlx_rs::{Array,Dtype,fast,nn,memory};
type Result<T>=std::result::Result<T,Box<dyn std::error::Error>>;
fn linear(x:&Array,w:&BTreeMap<String,Array>,name:&str)->Result<Array>{Ok(x.matmul(w[&format!("{name}.weight")].transpose()?)?)}
fn norm(x:&Array,w:&BTreeMap<String,Array>,name:&str,eps:f32)->Result<Array>{Ok(fast::rms_norm(x,Some(&w[&format!("{name}.weight")]),eps)?)}
fn infer(c:&Value,w:&BTreeMap<String,Array>,ids:&[Vec<i32>])->Result<Array>{
 let batch=ids.len() as i32;let length=ids[0].len() as i32;let hidden=c["hidden_size"].as_i64().ok_or("hidden")? as i32;
 let heads=c["num_attention_heads"].as_i64().ok_or("heads")? as i32;let kv=c["num_key_value_heads"].as_i64().ok_or("kv")? as i32;let head_dim=c["head_dim"].as_i64().ok_or("head dim")? as i32;
 let eps=c["rms_norm_eps"].as_f64().ok_or("eps")? as f32;let theta=c["rope_theta"].as_f64().ok_or("theta")? as f32;
 let input=Array::from_slice(&ids.iter().flatten().copied().collect::<Vec<_>>(),&[batch,length]);
 let mut x=w["embed_tokens.weight"].take_axis(&input,0)?;
 for layer in 0..c["num_hidden_layers"].as_i64().ok_or("layers")? {
  let p=format!("layers.{layer}");let normalized=norm(&x,w,&format!("{p}.input_layernorm"),eps)?;
  let queries=linear(&normalized,w,&format!("{p}.self_attn.q_proj"))?.reshape(&[batch,length,heads,head_dim])?;
  let keys=linear(&normalized,w,&format!("{p}.self_attn.k_proj"))?.reshape(&[batch,length,kv,head_dim])?;
  let values=linear(&normalized,w,&format!("{p}.self_attn.v_proj"))?.reshape(&[batch,length,kv,head_dim])?.transpose_axes(&[0,2,1,3])?;
  let queries=norm(&queries,w,&format!("{p}.self_attn.q_norm"),eps)?.transpose_axes(&[0,2,1,3])?;
  let keys=norm(&keys,w,&format!("{p}.self_attn.k_norm"),eps)?.transpose_axes(&[0,2,1,3])?;
  let queries=fast::rope(&queries,head_dim,false,Some(theta),1.0,0,None)?;
  let keys=fast::rope(&keys,head_dim,false,Some(theta),1.0,0,None)?;
  let mask=if length>1{Some(fast::ScaledDotProductAttentionMask::Causal)}else{None};
  let attention=fast::scaled_dot_product_attention(&queries,&keys,&values,(head_dim as f32).powf(-0.5),mask,None)?.transpose_axes(&[0,2,1,3])?.reshape(&[batch,length,heads*head_dim])?;
  x=x.add(linear(&attention,w,&format!("{p}.self_attn.o_proj"))?)?;
  let normalized=norm(&x,w,&format!("{p}.post_attention_layernorm"),eps)?;
  let gate=nn::silu(linear(&normalized,w,&format!("{p}.mlp.gate_proj"))?)?;
  let inner=gate.multiply(linear(&normalized,w,&format!("{p}.mlp.up_proj"))?)?;
  x=x.add(linear(&inner,w,&format!("{p}.mlp.down_proj"))?)?;
 }
 assert_eq!(x.shape(),[batch,length,hidden]);norm(&x,w,"norm",eps)
}
fn main()->Result<()>{
 let args:Vec<_>=std::env::args_os().collect();if args.len()!=3{return Err("usage: qwen-mlx-experiment SNAPSHOT REQUESTS".into());}
 let source=Path::new(&args[1]);let config:Value=serde_json::from_slice(&fs::read(source.join("config.json"))?)?;assert_eq!(config["model_type"],"qwen3");assert!(config["rope_scaling"].is_null());
 let prior=memory::set_cache_limit(512*1024*1024)?;if prior<512*1024*1024{memory::set_cache_limit(prior)?;}
 let requests:Value=serde_json::from_slice(&fs::read(&args[2])?)?;let mut outputs=Vec::new();let mut last=String::new();let mut weights=BTreeMap::new();
 for case in requests["cases"].as_array().ok_or("cases")?{
  let dtype=case["dtype"].as_str().ok_or("dtype")?;
  if dtype!=last{
   weights.clear();memory::clear_cache()?;
   let kind=match dtype{"float32"=>Dtype::Float32,"float16"=>Dtype::Float16,"bfloat16"=>Dtype::Bfloat16,_=>return Err("unsupported dtype".into())};
   for (key,value) in Array::load_safetensors(source.join("model.safetensors"))? {let value=value.as_dtype(kind)?;value.eval()?;weights.insert(key.strip_prefix("model.").unwrap_or(&key).to_owned(),value);}
   last=dtype.to_owned();
  }
  let ids:Vec<Vec<i32>>=serde_json::from_value(case["input_ids"].clone())?;let lengths:Vec<usize>=serde_json::from_value(case["real_lengths"].clone())?;
  let hidden=infer(&config,&weights,&ids)?.as_dtype(Dtype::Float32)?;hidden.eval()?;let actual=hidden.as_slice::<f32>().to_vec();
  let repeated=infer(&config,&weights,&ids)?.as_dtype(Dtype::Float32)?;repeated.eval()?;let repeat_exact=actual==repeated.as_slice::<f32>();
  let dim=hidden.shape()[2] as usize;let sequence=ids[0].len();let mut vectors=Vec::new();
  for (row,length) in lengths.iter().enumerate(){assert!(*length>0);let offset=(row*sequence+length-1)*dim;let state=&actual[offset..offset+dim];let norm=state.iter().map(|v|v*v).sum::<f32>().sqrt();assert!(norm>0.0);vectors.extend(state.iter().map(|v|v/norm));}
  let scores=if let Some(tokens)=case["projection_ids"].as_array(){
   assert_eq!(config["tie_word_embeddings"],true);assert_eq!(tokens.len(),2);
   let yes=Array::from_int(tokens[0].as_i64().ok_or("yes")? as i32);let no=Array::from_int(tokens[1].as_i64().ok_or("no")? as i32);
   let weight=&weights["embed_tokens.weight"];
   let difference=weight.take_axis(&yes,0)?.as_dtype(Dtype::Float32)?.subtract(weight.take_axis(&no,0)?.as_dtype(Dtype::Float32)?)?;
   let positions:Vec<i32>=lengths.iter().enumerate().map(|(i,len)|(i*sequence+len-1) as i32).collect();
   let indices=Array::from_slice(&positions,&[positions.len() as i32]);
   let states=hidden.reshape(&[-1,dim as i32])?.take_axis(&indices,0)?;
   let values=states.matmul(&difference)?;values.eval()?;Some(values.as_slice::<f32>().to_vec())
  }else{None};
  outputs.push(json!({"dtype":dtype,"hidden_shape":hidden.shape(),"hidden_f32":if case["include_hidden"]==false {None} else {Some(actual)},"vectors_f32":vectors,"scores_f32":scores,"original_indices":case["original_indices"],"repeat_exact":repeat_exact}));
 }
 println!("{}",json!({"format":"ken-mlx-qwen-native-viability/1","device":format!("{}",mlx_rs::Device::try_default()?),"cases":outputs,"model_inference_accepted":false}));Ok(())
}
