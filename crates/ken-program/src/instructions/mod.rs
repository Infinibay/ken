//! Ordered instructions separate immutable values, mutable places and control regions.
mod assembly;
mod lowering;
mod model;
mod verification;
use crate::ProgramError;
pub use lowering::lower;
pub use model::{Function, Instruction, Operand, Place, Program, Region};
type Result<T> = std::result::Result<T, ProgramError>;
impl Program {
    pub fn from_json(input: &str) -> Result<Self> {
        let program: Self = serde_json::from_str(input)?;
        program.verify()?;
        Ok(program)
    }
    pub fn to_json(&self) -> Result<String> {
        Ok(serde_json::to_string(self)?)
    }
    pub fn verify(&self) -> Result<()> {
        verification::verify(self)
    }
    pub fn format(&self) -> Result<String> {
        assembly::format(self)
    }
}
