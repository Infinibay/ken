//! Temporary CPU architecture experiment; not application code or an accepted backend.
use std::{collections::BTreeMap, fs, path::Path};
use serde_json::{Value, json};
use tch::{Device, Kind, Tensor};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn norm(x: &Tensor, weight: &Tensor, eps: f64) -> Tensor {
    let float=x.to_kind(Kind::Float);
    let variance=float.pow_tensor_scalar(2).mean_dim([-1_i64].as_slice(),true,Kind::Float);
    weight*(&float*(variance+eps).rsqrt()).to_kind(x.kind())
}
fn linear(x:&Tensor,weights:&BTreeMap<String,Tensor>,name:&str)->Tensor {
    x.matmul(&weights[&format!("{name}.weight")].transpose(0,1))
}
fn rotate(x:&Tensor,half:i64)->Tensor {
    Tensor::cat(&[-x.narrow(-1,half,half),x.narrow(-1,0,half)],-1)
}
fn repeat(x:&Tensor,groups:i64)->Tensor {
    let s=x.size();x.unsqueeze(2).expand([s[0],s[1],groups,s[2],s[3]],true).reshape([s[0],s[1]*groups,s[2],s[3]])
}
fn infer(config:&Value,w:&BTreeMap<String,Tensor>,ids:&[Vec<i64>],masks:&[Vec<i64>])->Result<(Tensor,Tensor)> {
    let device=w["model.embed_tokens.weight"].device();
    let n=ids.len() as i64;let s=ids[0].len() as i64;
    assert!(n>0&&s>0&&ids.iter().all(|v|v.len()==s as usize)&&masks.len()==n as usize&&masks.iter().all(|v|v.len()==s as usize));
    let h=config["head_dim"].as_i64().ok_or("head_dim")?;let heads=config["num_attention_heads"].as_i64().ok_or("heads")?;
    let kv=config["num_key_value_heads"].as_i64().ok_or("kv")?;let eps=config["rms_norm_eps"].as_f64().ok_or("eps")?;
    let hidden=config["hidden_size"].as_i64().ok_or("hidden")?;
    let id_tensor=Tensor::f_from_slice(&ids.iter().flatten().copied().collect::<Vec<_>>())?.to_device(device);
    let mut x=w["model.embed_tokens.weight"].index_select(0,&id_tensor).reshape([n,s,hidden]);
    let powers=Tensor::arange_start_step(0,h,2,(Kind::Int64,Device::Cpu)).to_kind(Kind::Float)/(h as f64);
    let inv=Tensor::full([h/2],config["rope_theta"].as_f64().ok_or("rope_theta")?,(Kind::Float,Device::Cpu)).pow(&powers).reciprocal().to_device(device);
    let positions=Tensor::arange(s,(Kind::Float,device));
    let frequencies=inv.reshape([1,h/2,1]).matmul(&positions.reshape([1,1,s])).transpose(1,2);
    let angles=Tensor::cat(&[&frequencies,&frequencies],-1);
    let cos=angles.cos().to_kind(x.kind()).unsqueeze(1);let sin=angles.sin().to_kind(x.kind()).unsqueeze(1);
    let has_padding=masks.iter().flatten().any(|v|*v==0);
    let allowed:Vec<u8>=masks.iter().flat_map(|m|(0..s as usize).flat_map(move|q|(0..s as usize).map(move|k|u8::from(k<=q&&m[k]!=0)))).collect();
    let mask=Tensor::f_from_slice(&allowed)?.to_kind(Kind::Bool).to_device(device).reshape([n,1,s,s]);
    for layer in 0..config["num_hidden_layers"].as_i64().ok_or("layers")? {
        let p=format!("model.layers.{layer}");
        let normalized=norm(&x,&w[&format!("{p}.input_layernorm.weight")],eps);
        let q=norm(&linear(&normalized,w,&format!("{p}.self_attn.q_proj")).reshape([n,s,heads,h]),&w[&format!("{p}.self_attn.q_norm.weight")],eps).transpose(1,2);
        let k=norm(&linear(&normalized,w,&format!("{p}.self_attn.k_proj")).reshape([n,s,kv,h]),&w[&format!("{p}.self_attn.k_norm.weight")],eps).transpose(1,2);
        let v=linear(&normalized,w,&format!("{p}.self_attn.v_proj")).reshape([n,s,kv,h]).transpose(1,2);
        let q=&q*&cos+rotate(&q,h/2)*&sin;let k=&k*&cos+rotate(&k,h/2)*&sin;
        let (k,v,gqa)=if has_padding{(repeat(&k,heads/kv),repeat(&v,heads/kv),false)}else{(k,v,true)};
        let attention=Tensor::f_scaled_dot_product_attention(&q,&k,&v,has_padding.then_some(&mask),0.0,!has_padding&&s>1,Some((h as f64).powf(-0.5)),gqa)?;
        let attention=attention.transpose(1,2).contiguous().reshape([n,s,heads*h]);
        x=&x+linear(&attention,w,&format!("{p}.self_attn.o_proj"));
        let normalized=norm(&x,&w[&format!("{p}.post_attention_layernorm.weight")],eps);
        let gate=linear(&normalized,w,&format!("{p}.mlp.gate_proj")).silu();
        x=&x+linear(&(gate*linear(&normalized,w,&format!("{p}.mlp.up_proj"))),w,&format!("{p}.mlp.down_proj"));
    }
    let hidden=norm(&x,&w["model.norm.weight"],eps);
    let rows:Vec<Tensor>=masks.iter().enumerate().map(|(row,mask)|{
        let last=mask.iter().rposition(|v|*v!=0);
        match last {Some(i)=>hidden.get(row as i64).get(i as i64),None=>Tensor::zeros([hidden.size()[2]],(hidden.kind(),device))}
    }).collect();
    let mut pooled=Tensor::stack(&rows,0);
    // Registered Normalize module, then encode(normalize_embeddings=true).
    for _ in 0..2 {let length=pooled.norm_scalaropt_dim(2.0,[-1_i64],true).clamp_min(1e-12);pooled=&pooled/length;}
    // Ken canonicalizes the outgoing vectors again in F32.
    let pooled=pooled.to_kind(Kind::Float);
    let vectors=&pooled/pooled.norm_scalaropt_dim(2.0,[-1_i64],true).clamp_min(1e-12);
    Ok((hidden,vectors))
}
fn main()->Result<()> {
    tch::set_num_threads(2);tch::set_num_interop_threads(1);let _guard=tch::no_grad_guard();
    let args:Vec<_>=std::env::args_os().collect();if args.len()!=3{return Err("usage: qwen-experiment SNAPSHOT REQUESTS".into());}
    let source=Path::new(&args[1]);let config:Value=serde_json::from_slice(&fs::read(source.join("config.json"))?)?;
    assert_eq!(config["model_type"],"qwen3");assert_eq!(config["attention_bias"],false);assert!(config["rope_scaling"].is_null());
    let requests:Value=serde_json::from_slice(&fs::read(&args[2])?)?;let mut outputs=Vec::new();
    for case in requests["cases"].as_array().ok_or("cases")? {
        let kind=match case["dtype"].as_str(){Some("float32")=>Kind::Float,Some("float16")=>Kind::Half,Some("bfloat16")=>Kind::BFloat16,_=>return Err("unsupported experiment dtype".into())};
        let device=match case["device"].as_str(){None|Some("cpu")=>Device::Cpu,Some("mps")=>Device::Mps,_=>return Err("unknown experiment device".into())};
        if device==Device::Mps{
            assert!(tch::utils::has_mps());
            #[cfg(target_os="macos")] {unsafe extern "C"{fn ken_mps_cap_experiment(fraction:f64,error:*mut std::ffi::c_char,length:usize)->std::ffi::c_int;}
              let mut error=[0_i8;1024];let status=unsafe{ken_mps_cap_experiment(0.7,error.as_mut_ptr(),error.len())};if status!=0{return Err(unsafe{std::ffi::CStr::from_ptr(error.as_ptr())}.to_string_lossy().into_owned().into());}}
        }
        let weights:BTreeMap<_,_>=Tensor::read_safetensors(source.join("model.safetensors"))?.into_iter().map(|(k,v)|(if k.starts_with("model."){k}else{format!("model.{k}")},v.to_kind(kind).to_device(device))).collect();
        let ids:Vec<Vec<i64>>=serde_json::from_value(case["input_ids"].clone())?;let masks:Vec<Vec<i64>>=serde_json::from_value(case["attention_mask"].clone())?;
        let (hidden,vectors)=infer(&config,&weights,&ids,&masks)?;let (repeated,_)=infer(&config,&weights,&ids,&masks)?;
        let repeat_exact=hidden.equal(&repeated);
        let scores=if let Some(ids)=case["projection_ids"].as_array(){
            assert_eq!(ids.len(),2);assert_eq!(config["tie_word_embeddings"],true);
            let weight=&weights["model.embed_tokens.weight"];
            let difference=weight.get(ids[0].as_i64().ok_or("true id")?).to_kind(Kind::Float)-weight.get(ids[1].as_i64().ok_or("false id")?).to_kind(Kind::Float);
            let states:Vec<_>=masks.iter().enumerate().map(|(row,m)|hidden.get(row as i64).get(m.iter().sum::<i64>()-1)).collect();
            Some(Vec::<f32>::try_from(&Tensor::stack(&states,0).to_kind(Kind::Float).matmul(&difference))?)
        }else{None};
        outputs.push(json!({"dtype":case["dtype"],"device":format!("{device:?}"),"hidden_shape":hidden.size(),"hidden_f32":if case["include_hidden"]==false {None}else{Some(Vec::<f32>::try_from(&hidden.to_kind(Kind::Float).to_device(Device::Cpu).reshape([-1]))?)},"vectors_f32":Vec::<f32>::try_from(&vectors.to_device(Device::Cpu).reshape([-1]))?,"scores_f32":scores,"repeat_exact":repeat_exact}));
    }
    println!("{}",json!({"format":"ken-qwen3-native-viability/1","cases":outputs,"model_inference_accepted":false}));Ok(())
}
