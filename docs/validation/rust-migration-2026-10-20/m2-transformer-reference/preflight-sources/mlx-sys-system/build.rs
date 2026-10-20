use std::{env,path::PathBuf};
#[path="src/bindgen_config.rs"] mod bindgen_config;
fn main(){
 let prefix=PathBuf::from(env::var_os("MLX_EXPERIMENT_PREFIX").expect("explicit isolated MLX prefix"));
 assert!(prefix.is_absolute());
 let version=std::fs::read_to_string(prefix.join("include/mlx/version.h")).expect("MLX version header");
 for expected in ["#define MLX_VERSION_MAJOR 0","#define MLX_VERSION_MINOR 32","#define MLX_VERSION_PATCH 3"]{assert!(version.contains(expected));}
 let root=PathBuf::from("src/mlx-c");
 let config_dir=PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap()).parent().unwrap().join("mlx-system-cmake");
 let mut config=cmake::Config::new(&root);
 config.profile("Release").define("MLX_C_USE_SYSTEM_MLX","ON").define("MLX_C_BUILD_EXAMPLES","OFF").define("MLX_DIR",&config_dir).define("CMAKE_C_COMPILER","/usr/bin/cc").define("CMAKE_CXX_COMPILER","/usr/bin/c++");
 let dst=config.build();
 println!("cargo:rustc-link-search=native={}/lib",dst.display());
 println!("cargo:rustc-link-search=native={}/lib",prefix.display());
 println!("cargo:rustc-link-lib=static=mlxc");println!("cargo:rustc-link-lib=dylib=mlx");println!("cargo:rustc-link-lib=c++");
 for framework in ["Metal","Foundation","QuartzCore","Accelerate"]{println!("cargo:rustc-link-lib=framework={framework}");}
 println!("cargo:rerun-if-env-changed=MLX_EXPERIMENT_PREFIX");
 let headers=bindgen_config::discover_headers(&root).expect("MLX C headers");
 let bindings=bindgen_config::builder(&root,&headers).generate().expect("MLX C declarations");
 bindings.write_to_file(PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("bindings.rs")).unwrap();
}
