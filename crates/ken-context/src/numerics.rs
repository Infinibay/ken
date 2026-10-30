//! Native stored-vector adapter. Numerical kernels stay with ken-retrieval;
//! allocation/liveness and segment decoding stay with ken-store.
use crate::{ContextNumerics, LiveScores, Result, VectorScores};
use ken_retrieval::vector_math::{NativeVectorMath, QueryNorm};
use rusqlite::Connection;
use std::path::Path;
#[derive(Default)]
pub struct NativeNumerics {
    math: Option<NativeVectorMath>,
}
impl NativeNumerics {
    fn math(&mut self) -> Result<&NativeVectorMath> {
        if self.math.is_none() {
            self.math = Some(NativeVectorMath::platform()?);
        }
        Ok(self.math.as_ref().expect("retained numerical owner"))
    }
}
impl ContextNumerics for NativeNumerics {
    fn normalize_query(&mut self, query: &[f32]) -> Result<Vec<f32>> {
        Ok(self
            .math()?
            .normalize_query(query, QueryNorm::AddEpsilon(1e-12))?)
    }
    fn rank_inline(&mut self, query: &[f32], blobs: &[Vec<u8>]) -> Result<VectorScores> {
        let rows = blobs.iter().map(|b| Some(b.as_slice())).collect::<Vec<_>>();
        let result = self.math()?.rank_against(query, &rows, false)?;
        Ok(VectorScores {
            kept: result.kept,
            scores: result.scores,
        })
    }
    fn live_scores(
        &mut self,
        conn: &Connection,
        root: Option<&Path>,
        space: &str,
        query: &[f32],
    ) -> Result<Option<LiveScores>> {
        let inferred = ken_knowledge::records::project_root(conn);
        let Some(root) = root.or(inferred.as_deref()) else {
            return Ok(None);
        };
        let directory = root.join(".ken/vectors");
        if !directory.is_dir() || !directory.join(format!("{space}.json")).is_file() {
            return Ok(None);
        }
        let space = space.parse::<ken_store::VectorSpace>()?;
        Ok(ken_retrieval::vector_store::live_store_scores(
            conn,
            Some(root),
            space,
            query,
            self.math()?,
        )?
        .map(|scores| LiveScores {
            slots: scores.slots,
            scores: scores.scores,
        }))
    }
    fn adaptive_threshold(&mut self, scores: &[f32], fixed: f64, enabled: bool) -> Result<f64> {
        if !enabled || scores.is_empty() {
            return Ok(fixed);
        }
        let (mean, std) = self.math()?.mean_std_f32(scores)?;
        Ok(fixed.min((f64::from(mean) + 1.5 * f64::from(std)).max(0.22)))
    }
    fn capped_indices(
        &mut self,
        scores: &[f32],
        threshold: f64,
        headroom: f64,
        cap: usize,
    ) -> Result<Vec<usize>> {
        let math = self.math()?;
        let keep = math.indices_at_least_f32(scores, threshold - headroom);
        if keep.len() <= cap {
            return Ok(keep);
        }
        let selected = keep.iter().map(|i| scores[*i]).collect::<Vec<_>>();
        let kth = if cap == 0 { 0 } else { keep.len() - cap };
        let partition = math.argpartition_f32(&selected, kth)?;
        Ok(partition[kth..].iter().map(|i| keep[*i]).collect())
    }
}
