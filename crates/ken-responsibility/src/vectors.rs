use crate::{LiveScores, RankedRows, Result};
use ken_retrieval::{
    DocumentEncoder, project_embeddings::ProjectEmbeddings, query_encoder::QueryEncoder,
    vector_math::NativeVectorMath, vector_store::live_store_scores,
};
use rusqlite::Connection;
use std::{path::Path, sync::Arc};
pub trait ResponsibilityVectors {
    fn embed_query(&mut self, text: &str) -> Result<Vec<f32>>;
    fn embed_passages(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn live_scores(
        &mut self,
        conn: &Connection,
        root: &Path,
        query: &[f32],
    ) -> Result<Option<LiveScores>>;
    fn rank_against(&mut self, query: &[f32], blobs: &[Vec<u8>]) -> Result<RankedRows>;
    fn cosine(
        &mut self,
        query: &[f32],
        flat: &[f32],
        rows: usize,
        width: usize,
    ) -> Result<Vec<f32>>;
}
pub struct NativeVectors {
    encoder: Arc<ProjectEmbeddings>,
    math: Option<NativeVectorMath>,
}
impl NativeVectors {
    pub fn new(encoder: Arc<ProjectEmbeddings>) -> Result<Self> {
        Ok(Self {
            encoder,
            math: None,
        })
    }
    fn math(&mut self) -> Result<&NativeVectorMath> {
        if self.math.is_none() {
            self.math = Some(NativeVectorMath::platform()?);
        }
        Ok(self.math.as_ref().expect("retained numerical owner"))
    }
}
impl ResponsibilityVectors for NativeVectors {
    fn embed_query(&mut self, text: &str) -> Result<Vec<f32>> {
        Ok(self.encoder.embed_query(&text.into())?)
    }
    fn embed_passages(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        Ok(self
            .encoder
            .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?)
    }
    fn live_scores(
        &mut self,
        conn: &Connection,
        root: &Path,
        query: &[f32],
    ) -> Result<Option<LiveScores>> {
        Ok(live_store_scores(
            conn,
            Some(root),
            ken_store::VectorSpace::IntentSources,
            query,
            self.math()?,
        )?
        .map(|s| LiveScores {
            slots: s.slots,
            scores: s.scores,
        }))
    }
    fn rank_against(&mut self, query: &[f32], blobs: &[Vec<u8>]) -> Result<RankedRows> {
        let blobs = blobs.iter().map(|b| Some(b.as_slice())).collect::<Vec<_>>();
        let s = self.math()?.rank_against(query, &blobs, false)?;
        Ok(RankedRows {
            kept: s.kept,
            scores: s.scores,
        })
    }
    fn cosine(
        &mut self,
        query: &[f32],
        flat: &[f32],
        rows: usize,
        width: usize,
    ) -> Result<Vec<f32>> {
        Ok(self.math()?.cosine_against(query, flat, rows, width)?)
    }
}
