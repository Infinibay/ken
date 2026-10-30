//! Explicit, scoped inference over caller-interpreted premises; no truth claims.
mod kernel;
mod model;
mod store;
pub use kernel::{Kernel, State};
pub use model::{Atom, Rule, digest, unify};
pub use store::{ask, ensure_schema, record};
