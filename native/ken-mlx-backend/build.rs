fn main() {
    println!("cargo:rustc-link-arg=-Wl,-rpath,@loader_path/lib");
}
