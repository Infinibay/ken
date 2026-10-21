fn main() {
    let prefix =
        std::env::var("LIBTORCH").expect("explicit manual pinned LIBTORCH prefix required");
    let os = std::env::var("CARGO_CFG_TARGET_OS").expect("target OS");
    println!("cargo:rerun-if-env-changed=LIBTORCH");
    println!("cargo:rerun-if-env-changed=LIBTORCH_CXX11_ABI");
    println!("cargo:rerun-if-changed=src/native-control.cpp");
    let abi = std::env::var("LIBTORCH_CXX11_ABI").expect("explicit native C++ ABI required");
    assert_eq!(abi, "1", "this manual native core is pinned to C++11 ABI1");
    cc::Build::new()
        .cpp(true)
        .file("src/native-control.cpp")
        .include(format!("{prefix}/include"))
        .include(format!("{prefix}/include/torch/csrc/api/include"))
        .flag("-std=c++17")
        .define("_GLIBCXX_USE_CXX11_ABI", abi.as_str())
        .compile("ken_torch_control");
    // Tests use the explicitly prepared core. Installed modules have only a
    // relative lookup into their privately owned authenticated core closure.
    println!("cargo:rustc-link-arg-tests=-Wl,-rpath,{prefix}/lib");
    if os == "macos" {
        println!("cargo:rustc-link-arg-cdylib=-Wl,-rpath,@loader_path/lib");
    } else if os == "linux" {
        // Link-time resolution of the full manual native closure, including
        // OpenBLAS's private Fortran dependency. This is never a runtime path.
        println!("cargo:rustc-link-arg=-Wl,-rpath-link,{prefix}/lib");
        println!("cargo:rustc-link-arg-cdylib=-Wl,-rpath,$ORIGIN/lib");
    }
}
