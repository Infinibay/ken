fn main(){
 if std::env::var("CARGO_CFG_TARGET_OS").as_deref()==Ok("macos"){
  let prefix=std::env::var("LIBTORCH").expect("manual pinned libtorch");
  cc::Build::new().cpp(true).file("src/mps-cap.cpp").include(format!("{prefix}/include")).include(format!("{prefix}/include/torch/csrc/api/include")).flag("-std=c++17").define("_GLIBCXX_USE_CXX11_ABI","1").compile("ken_mps_cap_experiment");
  println!("cargo:rerun-if-changed=src/mps-cap.cpp");
 }
}
