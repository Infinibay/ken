//! Pinned Snowball3.0.1 English; provenance and license in resources/snowball/.
mod among;
mod english;
mod runtime;
use among::Among;
use runtime::SnowballEnv;
pub(super) fn stem(value: &str) -> String {
    let mut env = SnowballEnv::create(value);
    english::stem(&mut env);
    env.get_current().into_owned()
}
