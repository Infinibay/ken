use ken_models::{EmbeddingSession, FastEmbedCatalog, FastEmbedDeviceRequest, FastEmbedInput, ModelFileSource, NativeOnnxRuntime};
use serde_json::{Value,json};
use std::{path::Path,sync::Arc,io::{self,Read}};
fn main()->Result<(),Box<dyn std::error::Error>>{
 let args:Vec<_>=std::env::args().collect();let mut input=String::new();io::stdin().read_to_string(&mut input)?;let request:Value=serde_json::from_str(&input)?;
 let catalog=FastEmbedCatalog::from_json(&std::fs::read_to_string(&args[1])?)?;let model=catalog.model(request["model"].as_str().unwrap())?;
 let source=Path::new(&args[2]).join(model.source_id().replace('/',"--")).join(model.source_revision());let source=ModelFileSource::new(&source,Path::new(&args[3]))?;
 let files=Arc::new(model.assets().verify_files(&source)?);let tokenizer=model.tokenizer_from_files(&files)?;
 let runtime=NativeOnnxRuntime::from_json(&std::fs::read_to_string(&args[4])?,Path::new(&args[5]))?;
 let mut session=EmbeddingSession::prepare(model,files,runtime,&FastEmbedDeviceRequest::from_inputs(Some("cpu"),None))?;let mut results=Vec::new();
 for case in request["cases"].as_array().unwrap(){
  let texts:Vec<_>=case["texts"].as_array().unwrap().iter().map(|value|value.as_str().unwrap()).collect();let side=if case["side"]=="query"{FastEmbedInput::Query}else{FastEmbedInput::Passage};
  let mut vectors=Vec::new();let mut batches=Vec::new();for tokens in tokenizer.tokenize(&texts,side)?{let batch=session.run(&tokens)?;vectors.extend(batch.vectors);batches.push(batch.trace);}
  let bytes:Vec<u8>=vectors.iter().flatten().flat_map(|value|value.to_le_bytes()).collect();let hex:String=bytes.iter().map(|byte|format!("{byte:02x}")).collect();
  results.push(json!({"id":case["id"],"shape":[vectors.len(),model.dim()],"vectors_f32le_hex":hex,"batches":batches}));
 }
 println!("{}",json!({"model":model.name(),"preparation":session.preparation(),"threads":session.thread_policy(),"optimization":session.optimization(),"results":results}));Ok(())
}
