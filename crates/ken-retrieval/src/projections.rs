//! Prepare encodings outside writes and publish under the pinned profile tuple.
use crate::{
    DocumentEncoder, LexicalCounter, Passage, PassagePolicy, Result, RetrievalError, TokenCounter,
    embedding_store::{self, EmbeddingInput},
    encoder::EncoderLoader,
    representations::bounded_passage_text,
    storage,
};
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_store::{ProjectDatabase, WriteTransaction};
use rusqlite::{Connection, params};
use std::{
    cell::RefCell,
    collections::{BTreeMap, HashMap, HashSet},
    rc::Rc,
};
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum View {
    Identity,
    Behavior,
}
impl View {
    pub const ALL: [Self; 2] = [Self::Identity, Self::Behavior];
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Identity => "identity",
            Self::Behavior => "behavior",
        }
    }
    pub fn spec(self, profile: &RetrievalProfile) -> &EncoderSpec {
        match self {
            Self::Identity => &profile.identity,
            Self::Behavior => &profile.behavior,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredProfile {
    pub profile: Option<String>,
    pub fingerprint: Option<String>,
}
pub fn stored_profile(conn: &Connection) -> Result<StoredProfile> {
    let mut query=conn.prepare("SELECT key,value FROM meta WHERE key IN('retrieval_profile','retrieval_profile_fingerprint')")?;
    let values = query
        .query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
        })?
        .collect::<rusqlite::Result<HashMap<_, _>>>()?;
    Ok(StoredProfile {
        profile: values.get("retrieval_profile").cloned().flatten(),
        fingerprint: values
            .get("retrieval_profile_fingerprint")
            .cloned()
            .flatten(),
    })
}
#[derive(Clone, Debug)]
pub struct PreparedView {
    pub texts: Vec<String>,
    pub vectors: Vec<Vec<f32>>,
    pub revision: String,
}
#[derive(Clone, Debug)]
pub struct PreparedProjection {
    pub profile: RetrievalProfile,
    pub expected_profile: StoredProfile,
    pub views: BTreeMap<View, PreparedView>,
}
impl PreparedProjection {
    pub fn publish(&self, tx: &WriteTransaction<'_>, passage_ids: &[i64]) -> Result<()> {
        if stored_profile(tx.connection())? != self.expected_profile {
            return Err(RetrievalError::Version(
                "retrieval profile changed while encoding; retry indexing".into(),
            ));
        }
        for (view, data) in &self.views {
            if passage_ids.len() != data.texts.len() || data.vectors.len() != data.texts.len() {
                return Err(RetrievalError::Invalid(
                    "source and prepared projection lengths differ".into(),
                ));
            }
            let entries: Vec<_> = passage_ids
                .iter()
                .zip(&data.texts)
                .zip(&data.vectors)
                .map(|((&passage_id, text), vector)| EmbeddingInput {
                    passage_id,
                    text: text.clone(),
                    vector: vector.clone(),
                })
                .collect();
            embedding_store::put_embeddings(tx, view.as_str(), &data.revision, &entries)?;
        }
        Ok(())
    }
}
pub struct ProjectionIndexer {
    pub profile: RetrievalProfile,
    legacy: LegacyRuntimeIdentity,
    expected_profile: StoredProfile,
    loader: Rc<dyn EncoderLoader>,
    encoders: RefCell<BTreeMap<View, Rc<dyn DocumentEncoder>>>,
}
impl ProjectionIndexer {
    pub fn new(
        conn: &Connection,
        profile: RetrievalProfile,
        legacy: LegacyRuntimeIdentity,
        loader: Rc<dyn EncoderLoader>,
    ) -> Result<Self> {
        profile.validate()?;
        Ok(Self {
            profile,
            legacy,
            expected_profile: stored_profile(conn)?,
            loader,
            encoders: RefCell::new(BTreeMap::new()),
        })
    }
    pub fn for_active(
        conn: &Connection,
        legacy: LegacyRuntimeIdentity,
        loader: Rc<dyn EncoderLoader>,
    ) -> Result<Option<Self>> {
        let stored = stored_profile(conn)?;
        let Some(raw) = stored.profile else {
            return Ok(None);
        };
        let profile = RetrievalProfile::from_json(&raw).map_err(|e| {
            RetrievalError::Version(format!("stored retrieval profile needs reindexing: {e}"))
        })?;
        if stored.fingerprint.as_deref() != Some(&profile.fingerprint(&legacy)?) {
            return Err(RetrievalError::Version(
                "retrieval runtime or projection changed; reindex the retrieval profile".into(),
            ));
        }
        Ok(Some(Self::new(conn, profile, legacy, loader)?))
    }
    pub fn encoder(&self, view: View) -> Result<Rc<dyn DocumentEncoder>> {
        if let Some(encoder) = self.encoders.borrow().get(&view) {
            return Ok(encoder.clone());
        }
        let encoder = self.loader.load(view.spec(&self.profile))?;
        self.encoders.borrow_mut().insert(view, encoder.clone());
        Ok(encoder)
    }
    pub fn policy(&self) -> Result<PassagePolicy> {
        let spec = &self.profile.behavior;
        let tokenizer = if self.profile.passage_tokenizer == "code-lexical-v1" {
            "code-lexical-v1".into()
        } else {
            format!(
                "{}@{}:tokenizer-v1:{}",
                spec.model_id,
                spec.revision,
                spec.tokenizer_revision(&self.legacy)?
            )
        };
        PassagePolicy::new(self.profile.max_tokens, tokenizer)
    }
    pub fn prepare(
        &self,
        conn: &Connection,
        files: &[&[Passage]],
    ) -> Result<Vec<PreparedProjection>> {
        let passages: Vec<_> = files.iter().flat_map(|p| p.iter()).collect();
        let mut views = BTreeMap::new();
        for view in View::ALL {
            let encoder = self.encoder(view)?;
            let texts = passages
                .iter()
                .map(|p| bounded_passage_text(p, view, &self.profile, encoder.as_ref()))
                .collect::<Result<Vec<_>>>()?;
            let revision = self.profile.vector_revision(view.as_str(), &self.legacy)?;
            let by_text = encode_texts(conn, view, &revision, &texts, encoder.as_ref())?;
            let vectors = texts.iter().map(|s| by_text[s].clone()).collect();
            views.insert(
                view,
                PreparedView {
                    texts,
                    vectors,
                    revision,
                },
            );
        }
        let mut out = Vec::new();
        let mut start = 0;
        for passages in files {
            let end = start + passages.len();
            let views = views
                .iter()
                .map(|(&view, data)| {
                    (
                        view,
                        PreparedView {
                            texts: data.texts[start..end].to_vec(),
                            vectors: data.vectors[start..end].to_vec(),
                            revision: data.revision.clone(),
                        },
                    )
                })
                .collect();
            out.push(PreparedProjection {
                profile: self.profile.clone(),
                expected_profile: self.expected_profile.clone(),
                views,
            });
            start = end;
        }
        Ok(out)
    }
}
impl TokenCounter for ProjectionIndexer {
    fn count(&self, text: &str) -> Result<usize> {
        if self.profile.passage_tokenizer == "code-lexical-v1" {
            LexicalCounter.count(text)
        } else {
            self.encoder(View::Behavior)?.token_count(text)
        }
    }
}
pub fn encode_texts(
    conn: &Connection,
    view: View,
    revision: &str,
    texts: &[String],
    encoder: &dyn DocumentEncoder,
) -> Result<HashMap<String, Vec<f32>>> {
    let mut seen = HashSet::new();
    let unique: Vec<_> = texts
        .iter()
        .filter(|s| seen.insert(s.as_str()))
        .cloned()
        .collect();
    if unique.is_empty() {
        return Ok(HashMap::new());
    }
    let dimension = encoder.dim()?;
    if dimension == 0 {
        return Err(RetrievalError::Invalid(
            "encoder dimension must be positive".into(),
        ));
    }
    let mut by_text = embedding_store::cached_embeddings(conn, view.as_str(), revision, &unique)?;
    for vector in by_text.values() {
        embedding_store::validated_norm(vector, Some(dimension)).map_err(|_| {
            RetrievalError::Version(
                "cached embedding dimensions differ from encoder; rebuild retrieval embeddings"
                    .into(),
            )
        })?;
    }
    let missing: Vec<_> = unique
        .iter()
        .filter(|s| !by_text.contains_key(*s))
        .cloned()
        .collect();
    if !missing.is_empty() {
        let input: Vec<_> = missing.iter().map(String::as_str).collect();
        let vectors = encoder.embed_passages(&input)?;
        if vectors.len() != missing.len() {
            return Err(RetrievalError::Invalid(
                "encoder returned a different number of embeddings".into(),
            ));
        }
        for vector in &vectors {
            embedding_store::validated_norm(vector, Some(dimension))?;
        }
        by_text.extend(missing.into_iter().zip(vectors));
    }
    Ok(by_text)
}
pub fn index_embeddings(
    db: &mut ProjectDatabase,
    profile: RetrievalProfile,
    legacy: LegacyRuntimeIdentity,
    loader: Rc<dyn EncoderLoader>,
) -> Result<()> {
    profile.validate()?;
    let snapshot = embedding_store::retrieval_snapshot(db.connection())?;
    let expected_profile = stored_profile(db.connection())?;
    let passages = storage::load_passage_map(db.connection(), None)?;
    let source_generation = snapshot.generation;
    snapshot.finish()?;
    if passages.is_empty() {
        return Err(RetrievalError::Invalid(
            "no source passages indexed; run source indexing first".into(),
        ));
    }
    let mut prepared = Vec::new();
    for view in View::ALL {
        let encoder = loader.load(view.spec(&profile))?;
        let texts = passages
            .iter()
            .map(|(id, p)| {
                Ok((
                    *id,
                    bounded_passage_text(p, view, &profile, encoder.as_ref())?,
                ))
            })
            .collect::<Result<Vec<_>>>()?;
        let revision = profile.vector_revision(view.as_str(), &legacy)?;
        let raw: Vec<_> = texts.iter().map(|(_, s)| s.clone()).collect();
        let encoded = encode_texts(db.connection(), view, &revision, &raw, encoder.as_ref())?;
        let texts =
            embedding_store::pending_texts(db.connection(), view.as_str(), &revision, &texts)?;
        if texts.is_empty() {
            continue;
        }
        let entries = texts
            .into_iter()
            .map(|(id, text)| EmbeddingInput {
                passage_id: id,
                vector: encoded[&text].clone(),
                text,
            })
            .collect::<Vec<_>>();
        prepared.push((view, revision, entries));
    }
    let tx = db.immediate()?;
    if storage::generation(tx.connection())? != source_generation {
        return Err(RetrievalError::Version(
            "source changed while encoding; retry indexing".into(),
        ));
    }
    if stored_profile(tx.connection())? != expected_profile {
        return Err(RetrievalError::Version(
            "retrieval profile changed while encoding; retry indexing".into(),
        ));
    }
    for (view, revision, entries) in &prepared {
        embedding_store::put_embeddings(&tx, view.as_str(), revision, entries)?;
    }
    tx.connection().execute("INSERT INTO meta(key,value)VALUES('retrieval_profile',?1)ON CONFLICT(key)DO UPDATE SET value=excluded.value",[profile.to_json()?])?;
    if !prepared.is_empty() {
        embedding_store::reclaim_retired(&tx, None)?;
    }
    for (key, value) in [
        (
            "retrieval_representation_version",
            profile.representation_version.to_string(),
        ),
        (
            "retrieval_profile_fingerprint",
            profile.fingerprint(&legacy)?,
        ),
    ] {
        tx.connection().execute("INSERT INTO meta(key,value)VALUES(?1,?2)ON CONFLICT(key)DO UPDATE SET value=excluded.value",params![key,value])?;
    }
    tx.commit()?;
    Ok(())
}
