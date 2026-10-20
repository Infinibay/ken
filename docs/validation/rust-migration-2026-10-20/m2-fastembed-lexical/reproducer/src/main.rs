use ken_models::{FastEmbedCatalog, FastEmbedInput, ModelFileSource};
use serde_json::{Value, json};
use std::{io::{self, BufRead},path::Path};
fn main() -> Result<(), Box<dyn std::error::Error>> {
 let args:Vec<_>=std::env::args().collect();
 let catalog=FastEmbedCatalog::from_json(&std::fs::read_to_string(&args[1])?)?;
 for line in io::stdin().lock().lines() {
  let request:Value=serde_json::from_str(&line?)?;
  let name=request["model"].as_str().unwrap();
  let model=catalog.model(name)?.with_requested_name(name)?;
  let source=Path::new(&args[2]).join(model.source_id().replace('/',"--")).join(model.source_revision());
  let source=ModelFileSource::new(&source,Path::new(&args[3]))?;
  let tokenizer=model.tokenizer(&source)?;
  let mut results=Vec::new();
  for case in request["cases"].as_array().unwrap() {
   let texts:Vec<_>=case["texts"].as_array().unwrap().iter().map(|value|value.as_str().unwrap()).collect();
   let side=match case["side"].as_str().unwrap(){"query"=>FastEmbedInput::Query,"passage"=>FastEmbedInput::Passage,_=>panic!("side")};
   let batches=tokenizer.tokenize(&texts,side)?;
   results.push(json!({"id":case["id"],"batches":batches.iter().map(|batch|json!({"shape":batch.shape,"ids":batch.ids,"attention_mask":batch.attention_mask})).collect::<Vec<_>>()}));
  }
  println!("{}",json!({"model":name,"results":results}));
 }
 Ok(())
}
