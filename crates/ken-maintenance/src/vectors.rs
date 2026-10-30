//! Maintenance decisions wrap authoritative storage operations and advisory reclamation.
use crate::{MaintenanceApplication, Result};
use ken_store::{MaintenanceEvent, ProjectDatabase, VectorSpace};
use serde_json::{Value, json};
#[derive(Clone, Copy, Debug, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum VectorAction {
    Status,
    Verify,
    Migrate,
    Compact,
}
pub trait DatabaseReclaimer {
    fn reclaim(&mut self, database: &mut ProjectDatabase) -> Result<(u64, u64)>;
}
pub struct NativeReclaimer;
impl DatabaseReclaimer for NativeReclaimer {
    fn reclaim(&mut self, database: &mut ProjectDatabase) -> Result<(u64, u64)> {
        Ok(ken_store::reclaim_database(database)?)
    }
}
impl MaintenanceApplication {
    pub fn vectors(
        &mut self,
        action: VectorAction,
        dim: usize,
        model: Option<&str>,
        progress: &mut impl FnMut(MaintenanceEvent),
    ) -> Result<Value> {
        self.vectors_with_reclaimer(action, dim, model, &mut NativeReclaimer, progress)
    }
    pub fn vectors_with_reclaimer(
        &mut self,
        action: VectorAction,
        dim: usize,
        model: Option<&str>,
        reclaimer: &mut dyn DatabaseReclaimer,
        progress: &mut impl FnMut(MaintenanceEvent),
    ) -> Result<Value> {
        let mut out = json!({"action":action,"path":self.paths.root(),"dim":dim});
        match action {
            VectorAction::Migrate => {
                let moved = ken_store::migrate_inline(&mut self.store, dim, model, 2000, progress)?;
                if moved.values().any(|count| *count > 0) {
                    match reclaimer.reclaim(self.store.database_mut()) {
                        Ok((before, after)) => {
                            out["db_bytes_before"] = json!(before);
                            out["db_bytes_after"] = json!(after);
                        }
                        Err(error) => out["vacuum_error"] = json!(error.to_string()),
                    }
                }
                out["moved"] = serde_json::to_value(moved)?;
            }
            VectorAction::Compact => {
                out["compacted"] =
                    serde_json::to_value(ken_store::compact(&mut self.store, dim, progress)?)?
            }
            VectorAction::Status | VectorAction::Verify => {
                let mut spaces = serde_json::Map::new();
                for space in VectorSpace::ALL {
                    let inline: i64 = self.store.database().connection().query_row(
                        &format!("SELECT COUNT(*) FROM {space} WHERE embedding IS NOT NULL"),
                        [],
                        |r| r.get(0),
                    )?;
                    let info = match self.store.vectors(space, dim, None) {
                        Ok(store) => {
                            let mut value = if matches!(action, VectorAction::Verify) {
                                serde_json::to_value(ken_store::verify(
                                    self.store.database().connection(),
                                    &store,
                                )?)?
                            } else {
                                json!({})
                            };
                            value["inline_pending"] = json!(inline);
                            value["bytes"] = json!(store.bytes_on_disk()?);
                            value
                        }
                        Err(error) => json!({"error":error.to_string(),"inline":inline}),
                    };
                    spaces.insert(space.as_str().into(), info);
                }
                out["spaces"] = Value::Object(spaces);
            }
        }
        Ok(out)
    }
}
