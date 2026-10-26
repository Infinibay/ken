#[path = "x86_features.rs"]
mod capabilities;
fn main() {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    println!("{}", capabilities::json());
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    panic!("execution profiles require Linux x86_64");
}
