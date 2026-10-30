fn main() {
    println!("cargo:rerun-if-changed=src/vector_math/sort_fallback.cpp");
    cc::Build::new()
        .cpp(true)
        .std("c++17")
        .file("src/vector_math/sort_fallback.cpp")
        .compile("ken_vector_sort");
}
