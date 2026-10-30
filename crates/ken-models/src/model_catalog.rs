//! Registered families and compatible identities; this catalog never opens data.
use crate::{
    ContextModel, EncoderBackend, EncoderSpec, FastEmbedCatalog, FastEmbedModel,
    LegacyRuntimeIdentity, ModelAssets, ModelError, RerankerModel, TransformerArchitecture,
    TransformerDtype, TransformerModel, TransformerRole, TransformerSettings, TranslationModel,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EncoderFamily {
    StaticTable,
    Potion,
    FastEmbed,
    SentenceTransformer,
    Mlx,
}

#[derive(Clone, Deserialize)]
pub(crate) struct StaticRegistration {
    pub(crate) model_id: String,
    pub(crate) bytes: u64,
    pub(crate) sha256: String,
}

pub(crate) enum EncoderDefinition {
    Static(StaticRegistration),
    Potion(ModelAssets),
    FastEmbed(FastEmbedModel),
    Sentence(TransformerModel, TransformerSettings),
    Mlx(TransformerModel, TransformerSettings),
}
impl EncoderDefinition {
    pub(crate) fn family(&self) -> EncoderFamily {
        match self {
            Self::Static(_) => EncoderFamily::StaticTable,
            Self::Potion(_) => EncoderFamily::Potion,
            Self::FastEmbed(_) => EncoderFamily::FastEmbed,
            Self::Sentence(..) => EncoderFamily::SentenceTransformer,
            Self::Mlx(..) => EncoderFamily::Mlx,
        }
    }
}

/// Registered metadata only. Listing never acquires assets or promises unqualified inference.
#[derive(Clone, Debug, Serialize)]
pub struct ModelDescriptor {
    pub model: String,
    pub dim: Option<usize>,
    pub bytes: u64,
    pub backend: EncoderFamily,
    pub registration: ModelRegistration,
    pub native_inference_accepted: bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct ModelRegistration {
    pub model_id: String,
    pub revision: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assets: Option<ModelAssets>,
}
pub struct ModelCatalog {
    pub(crate) static_table: StaticRegistration,
    pub(crate) potion: ModelAssets,
    pub(crate) context: ContextModel,
    pub(crate) reranker: RerankerModel,
    pub(crate) translation: TranslationModel,
    fastembed: FastEmbedCatalog,
    extensions: Vec<crate::CatalogExtensions>,
    transformers: Vec<TransformerModel>,
    compatible: BTreeMap<EncoderBackend, Vec<Vec<(String, String)>>>,
}

impl ModelCatalog {
    pub fn built_in() -> Result<Self, ModelError> {
        #[derive(Deserialize)]
        struct Compatibility {
            format: String,
            backends: BTreeMap<EncoderBackend, Vec<Vec<(String, String)>>>,
            static_table: StaticRegistration,
        }
        let compatibility: Compatibility =
            serde_json::from_str(include_str!("../resources/legacy-compatibility.json"))?;
        if compatibility.format != "ken-registered-legacy-compatibility/1" {
            return Err(crate::profile::invalid(
                "registered legacy compatibility required",
            ));
        }
        let transformers: serde_json::Value =
            serde_json::from_str(include_str!("../resources/transformer-catalog.json"))?;
        let transformers = transformers["models"]
            .as_array()
            .ok_or_else(|| crate::profile::invalid("registered transformers required"))?
            .iter()
            .map(|value| TransformerModel::from_json(&value.to_string()))
            .collect::<Result<_, _>>()?;
        Ok(Self {
            static_table: compatibility.static_table,
            potion: ModelAssets::from_json(include_str!("../resources/potion-code-16M-v2.json"))?,
            context: ContextModel::from_json(include_str!("../resources/code-context-int8.json"))?,
            reranker: RerankerModel::from_json(include_str!("../resources/ettin-68m-fp32.json"))?,
            translation: TranslationModel::from_json(include_str!(
                "../resources/es-en-ct2-int8.json"
            ))?,
            fastembed: FastEmbedCatalog::from_json(include_str!(
                "../resources/fastembed-catalog.json"
            ))?,
            transformers,
            extensions: Vec::new(),
            compatible: compatibility.backends,
        })
    }

    pub fn models(&self) -> Vec<ModelDescriptor> {
        let descriptor =
            |name: String, dim: Option<usize>, backend, assets: &ModelAssets| ModelDescriptor {
                model: name,
                dim,
                bytes: assets
                    .artifact_records()
                    .values()
                    .map(|item| item.bytes)
                    .sum(),
                backend,
                registration: ModelRegistration {
                    model_id: assets.model_id().into(),
                    revision: assets.revision().into(),
                    assets: Some(assets.clone()),
                },
                native_inference_accepted: false,
            };
        let mut result = vec![
            ModelDescriptor {
                model: self.static_table.model_id.clone(),
                dim: None,
                bytes: self.static_table.bytes,
                backend: EncoderFamily::StaticTable,
                registration: ModelRegistration {
                    model_id: self.static_table.model_id.clone(),
                    revision: self.static_table.sha256.clone(),
                    assets: None,
                },
                native_inference_accepted: false,
            },
            descriptor(
                self.potion.model_id().into(),
                None,
                EncoderFamily::Potion,
                &self.potion,
            ),
        ];
        result.extend(self.fastembed.models().iter().map(|model| {
            descriptor(
                model.name().into(),
                Some(model.dim()),
                EncoderFamily::FastEmbed,
                model.assets(),
            )
        }));
        result.extend(
            self.transformers
                .iter()
                .filter(|model| model.role() == TransformerRole::Encoder)
                .map(|model| {
                    descriptor(
                        model.assets().model_id().into(),
                        Some(model.dimension()),
                        EncoderFamily::SentenceTransformer,
                        model.assets(),
                    )
                }),
        );
        result.extend(
            self.extensions
                .iter()
                .flat_map(|extension| extension.entries())
                .map(|entry| entry.descriptor()),
        );
        result
    }

    /// Compose additional immutable encoders without shadowing established names.
    pub fn with_extensions(
        mut self,
        extension: crate::CatalogExtensions,
    ) -> Result<Self, ModelError> {
        let mut names = std::collections::BTreeSet::new();
        names.insert(self.static_table.model_id.to_lowercase());
        names.insert(self.potion.model_id().to_lowercase());
        names.extend(
            self.fastembed
                .models()
                .iter()
                .map(|model| model.name().to_lowercase()),
        );
        names.extend(
            self.transformers
                .iter()
                .map(|model| model.assets().model_id().to_lowercase()),
        );
        names.extend(
            self.extensions
                .iter()
                .flat_map(|extension| extension.entries())
                .map(|entry| entry.name().to_lowercase()),
        );
        for entry in extension.entries() {
            if !names.insert(entry.name().to_lowercase()) {
                return Err(crate::profile::invalid(
                    "catalogue extension conflicts with a registered model name",
                ));
            }
        }
        self.extensions.push(extension);
        Ok(self)
    }

    pub fn extension_selector(&self, name: &str) -> Result<String, ModelError> {
        self.extension_named(name)
            .map(|entry| entry.selector().to_owned())
    }

    pub fn extension_spec(&self, name: &str) -> Result<EncoderSpec, ModelError> {
        self.extension_named(name)?.spec()
    }

    pub fn extension_status(
        &self,
        selector: &str,
        snapshot: Option<&std::path::Path>,
    ) -> Result<crate::ExtensionStatus, ModelError> {
        self.extension_selected(selector)?.status(snapshot)
    }

    fn extension_named(&self, name: &str) -> Result<&crate::catalog_extensions::Entry, ModelError> {
        self.extensions
            .iter()
            .find_map(|extension| extension.name(name))
            .ok_or_else(|| crate::profile::invalid("unregistered additional encoder name"))
    }

    fn extension_selected(
        &self,
        selector: &str,
    ) -> Result<&crate::catalog_extensions::Entry, ModelError> {
        self.extensions
            .iter()
            .find_map(|extension| extension.selector(selector))
            .ok_or_else(|| crate::profile::invalid("unregistered immutable catalogue selector"))
    }

    pub fn static_spec(&self) -> EncoderSpec {
        EncoderSpec {
            model_id: self.static_table.model_id.clone(),
            revision: self.static_table.sha256.clone(),
            backend: EncoderBackend::Static,
            dtype: TransformerDtype::Float32,
            sequence_length: 512,
            batch_size: 16,
        }
    }

    pub fn potion_spec(&self) -> EncoderSpec {
        EncoderSpec {
            model_id: self.potion.model_id().into(),
            revision: self.potion.fingerprint(),
            backend: EncoderBackend::Model2Vec,
            dtype: TransformerDtype::Float16,
            sequence_length: 512,
            batch_size: 1024,
        }
    }

    pub(crate) fn accredit(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<(), ModelError> {
        spec.validate()?;
        let actual = legacy.backend(spec.backend)?;
        if !self
            .compatible
            .get(&spec.backend)
            .is_some_and(|known| known.iter().any(|versions| versions == actual))
        {
            return Err(crate::profile::invalid(
                "unaccredited original runtime for registered native model",
            ));
        }
        Ok(())
    }

    fn transformer(
        &self,
        spec: &EncoderSpec,
        role: TransformerRole,
    ) -> Result<TransformerModel, ModelError> {
        let model = self
            .transformers
            .iter()
            .find(|model| {
                model.assets().model_id() == spec.model_id
                    && model.assets().revision() == spec.revision
                    && model.role() == role
            })
            .cloned()
            .or_else(|| {
                self.extensions
                    .iter()
                    .flat_map(|extension| extension.entries())
                    .find_map(|entry| entry.transformer_for(spec, role))
            })
            .ok_or_else(|| crate::profile::invalid("unregistered transformer identity or role"))?;
        if spec.backend == EncoderBackend::Mlx
            && model.architecture() != TransformerArchitecture::Qwen3
        {
            return Err(crate::profile::invalid(
                "MLX requires a registered Qwen3 architecture",
            ));
        }
        Ok(model.clone())
    }

    pub(crate) fn encoder(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<EncoderDefinition, ModelError> {
        self.accredit(spec, legacy)?;
        let settings = TransformerSettings {
            dtype: Some(spec.dtype),
            sequence_length: Some(spec.sequence_length),
            batch_size: Some(spec.batch_size),
        };
        match spec.backend {
            EncoderBackend::Static
                if spec.model_id == self.static_table.model_id
                    && spec.revision == self.static_table.sha256 =>
            {
                Ok(EncoderDefinition::Static(self.static_table.clone()))
            }
            EncoderBackend::Model2Vec if spec == &self.potion_spec() => {
                Ok(EncoderDefinition::Potion(self.potion.clone()))
            }
            EncoderBackend::SentenceTransformers => Ok(EncoderDefinition::Sentence(
                self.transformer(spec, TransformerRole::Encoder)?,
                settings,
            )),
            EncoderBackend::Mlx => Ok(EncoderDefinition::Mlx(
                self.transformer(spec, TransformerRole::Encoder)?,
                settings,
            )),
            EncoderBackend::Provided => Err(crate::profile::invalid(
                "provided encoders require explicit dependency injection",
            )),
            _ => Err(crate::profile::invalid(
                "encoder does not match its registered pinned profile",
            )),
        }
    }

    pub(crate) fn judge(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<TransformerModel, ModelError> {
        self.accredit(spec, legacy)?;
        if !matches!(
            spec.backend,
            EncoderBackend::SentenceTransformers | EncoderBackend::Mlx
        ) {
            return Err(crate::profile::invalid(
                "judge requires an explicit transformer backend",
            ));
        }
        self.transformer(spec, TransformerRole::Judge)
    }

    pub(crate) fn legacy_encoder(&self, name: &str) -> Result<EncoderDefinition, ModelError> {
        if name == self.static_table.model_id {
            return Ok(EncoderDefinition::Static(self.static_table.clone()));
        }
        if name == self.potion.model_id() {
            return Ok(EncoderDefinition::Potion(self.potion.clone()));
        }
        if let Ok(model) = self.fastembed.model(name) {
            return Ok(EncoderDefinition::FastEmbed(
                model.with_requested_name(name)?,
            ));
        }
        if let Some(model) = self.transformers.iter().find(|model| {
            model.assets().model_id() == name && model.role() == TransformerRole::Encoder
        }) {
            return Ok(EncoderDefinition::Sentence(
                model.clone(),
                TransformerSettings::default(),
            ));
        }
        if let Ok(entry) = self.extension_selected(name) {
            return Ok(entry.definition());
        }
        Err(crate::profile::invalid(
            "unregistered legacy encoder name or non-encoder role; additional models require their immutable catalogue selector",
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        AcquisitionPolicy, ArtifactCache, ContextInput, ModelFactory, NativeOnnxRuntime,
        PreparedModelResources, SentenceEncoder, TransformerDeviceRequest,
    };
    use serde_json::Value;
    use std::{
        fs,
        path::{Path, PathBuf},
    };

    fn fixtures() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
    }
    fn copy_tree(source: &Path, destination: &Path) {
        fs::create_dir_all(destination).unwrap();
        for entry in fs::read_dir(source).unwrap() {
            let entry = entry.unwrap();
            let target = destination.join(entry.file_name());
            if entry.file_type().unwrap().is_dir() {
                copy_tree(&entry.path(), &target);
            } else {
                fs::copy(entry.path(), target).unwrap();
            }
        }
    }
    fn legacy(file: &str) -> LegacyRuntimeIdentity {
        let value: Value = serde_json::from_slice(
            &fs::read(fixtures().join("profile-identity").join(file)).unwrap(),
        )
        .unwrap();
        LegacyRuntimeIdentity::from_json(&value["legacy_runtime"].to_string()).unwrap()
    }
    fn resources(root: &Path) -> PreparedModelResources {
        PreparedModelResources::new(&root.join("owned"), &root.join("table.npz")).unwrap()
    }
    fn factory(
        catalog: ModelCatalog,
        resources: PreparedModelResources,
        root: &Path,
    ) -> ModelFactory {
        ModelFactory::new(
            catalog,
            ArtifactCache::new(&root.join("cache")).unwrap(),
            resources,
            AcquisitionPolicy::Offline,
        )
    }
    fn onnx() -> NativeOnnxRuntime {
        NativeOnnxRuntime::from_json(
            include_str!("../resources/onnx-runtime-libraries.json"),
            &PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").expect("prepare real ONNX runtime")),
        )
        .unwrap()
    }

    #[test]
    fn factory_potion_retries_missing_and_corrupt_files_then_owns_original_vectors() {
        let root = tempfile::tempdir().unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.potion =
            ModelAssets::from_json(include_str!("../tests/fixtures/float16/registration.json"))
                .unwrap();
        let spec = catalog.potion_spec();
        let source = root.path().join("borrowed").join(catalog.potion.revision());
        let mut prepared = resources(root.path());
        prepared
            .source_overrides
            .insert(spec.model_id.clone(), source.clone());
        let factory = factory(catalog, prepared, root.path());
        let encoder = factory.encoder(&spec, &legacy("macos.json")).unwrap();
        assert!(encoder.embed_query("a b").is_err());
        assert!(!encoder.is_prepared().unwrap());
        copy_tree(&fixtures().join("float16").join("2".repeat(40)), &source);
        let weights = fs::read(source.join("model.safetensors")).unwrap();
        fs::write(source.join("model.safetensors"), b"bad").unwrap();
        assert!(encoder.dim().is_err());
        assert!(!encoder.is_prepared().unwrap());
        fs::write(source.join("model.safetensors"), weights).unwrap();
        assert_eq!(encoder.dim().unwrap(), 3);
        assert_eq!(encoder.token_count("a b").unwrap(), 2);
        let expected: Value =
            serde_json::from_str(include_str!("../tests/fixtures/float16/reference.json")).unwrap();
        let vector = encoder.embed_query("a b").unwrap();
        for (actual, original) in vector.iter().zip(
            expected["results"][0]["calls"][0]["vectors"][0]
                .as_array()
                .unwrap(),
        ) {
            assert!((*actual as f64 - original.as_f64().unwrap()).abs() < 2e-6);
        }
        fs::remove_dir_all(&source).unwrap();
        assert_eq!(encoder.embed_query("a b").unwrap(), vector);
        assert!(encoder.is_prepared().unwrap());
    }

    #[test]
    fn actual_concurrent_potion_first_use_shares_one_adapter_and_owned_results() {
        let root = tempfile::tempdir().unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.potion =
            ModelAssets::from_json(include_str!("../tests/fixtures/float16/registration.json"))
                .unwrap();
        let spec = catalog.potion_spec();
        let source = root.path().join(catalog.potion.revision());
        copy_tree(
            &fixtures().join("float16").join(catalog.potion.revision()),
            &source,
        );
        let mut prepared = resources(root.path());
        prepared
            .source_overrides
            .insert(spec.model_id.clone(), source.clone());
        let factory = factory(catalog, prepared, root.path());
        let runtime = legacy("macos.json");
        let encoder = factory.encoder(&spec, &runtime).unwrap();
        let vectors = std::thread::scope(|scope| {
            let jobs: Vec<_> = (0..8)
                .map(|_| {
                    scope.spawn(|| {
                        factory
                            .encoder(&spec, &runtime)
                            .unwrap()
                            .embed_query("a")
                            .unwrap()
                    })
                })
                .collect();
            jobs.into_iter()
                .map(|job| job.join().unwrap())
                .collect::<Vec<_>>()
        });
        assert!(vectors.iter().all(|v| v == &vectors[0]));
        let mut mutated = vectors[0].clone();
        mutated[0] = 100.;
        assert_ne!(encoder.embed_query("a").unwrap(), mutated);
        fs::remove_dir_all(source).unwrap();
        assert_eq!(encoder.embed_query("a").unwrap(), vectors[0]);
    }

    #[test]
    fn actual_static_table_loads_lazily_and_survives_removal_of_its_npz() {
        use sha2::{Digest, Sha256};
        let root = tempfile::tempdir().unwrap();
        let bytes = fs::read(fixtures().join("table/f16.npz")).unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.static_table = StaticRegistration {
            model_id: "test/table".into(),
            bytes: bytes.len() as u64,
            sha256: format!("{:x}", Sha256::digest(&bytes)),
        };
        let spec = catalog.static_spec();
        let prepared = resources(root.path());
        fs::write(&prepared.bundled_npz, &bytes).unwrap();
        let path = prepared.bundled_npz.clone();
        let factory = factory(catalog, prepared, root.path());
        let encoder = factory.encoder(&spec, &legacy("macos.json")).unwrap();
        assert!(!encoder.is_prepared().unwrap());
        assert!(encoder.embed_passages(&[]).unwrap().is_empty());
        assert!(!encoder.is_prepared().unwrap());
        let original = crate::StaticTableEncoder::from_npz(&bytes).unwrap();
        assert_eq!(
            encoder.embed_query("clearAuth").unwrap(),
            original.embed_query("clearAuth").unwrap()
        );
        assert_eq!(encoder.dim().unwrap(), 4);
        fs::remove_file(path).unwrap();
        assert_eq!(
            encoder.token_count("clearAuth").unwrap(),
            original.token_count("clearAuth").unwrap()
        );
    }

    #[test]
    fn actual_torch_factory_forwards_the_profile_and_keeps_owned_weights_after_source_removal() {
        let (root, model, source, runtime) =
            crate::transformer_test_support::fixture_with_configs(&[]);
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.transformers = vec![model.clone()];
        let spec = EncoderSpec {
            model_id: model.assets().model_id().into(),
            revision: model.assets().revision().into(),
            backend: EncoderBackend::SentenceTransformers,
            dtype: TransformerDtype::Float32,
            sequence_length: 16,
            batch_size: 4,
        };
        let settings = TransformerSettings {
            dtype: Some(spec.dtype),
            sequence_length: Some(16),
            batch_size: Some(4),
        };
        let direct = SentenceEncoder::new(
            model,
            source.clone(),
            runtime.clone(),
            settings,
            TransformerDeviceRequest::Cpu,
        )
        .unwrap();
        let expected = direct.embed_query("red").unwrap();
        let mut prepared = resources(root.path());
        prepared.torch = Some(runtime);
        prepared.transformer_device = TransformerDeviceRequest::Cpu;
        prepared
            .source_overrides
            .insert(spec.model_id.clone(), source.snapshot().into());
        let factory = factory(catalog, prepared, root.path());
        let encoder = factory.encoder(&spec, &legacy("macos-torch.json")).unwrap();
        assert!(!encoder.is_prepared().unwrap());
        assert!(encoder.token_count("red").unwrap() > 0);
        assert!(!encoder.is_prepared().unwrap());
        assert_eq!(encoder.embed_query("red").unwrap(), expected);
        fs::remove_dir_all(source.snapshot()).unwrap();
        assert_eq!(encoder.embed_query("red").unwrap(), expected);
    }

    #[test]
    fn deferred_context_retries_then_retains_its_authenticated_graph_and_tokenizer() {
        let root = tempfile::tempdir().unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.context = ContextModel::from_json(include_str!(
            "../tests/fixtures/context/valid/definition.json"
        ))
        .unwrap();
        let source = root.path().join(catalog.context.assets().revision());
        let mut prepared = resources(root.path());
        prepared.onnx = Some(onnx());
        prepared
            .source_overrides
            .insert(catalog.context.assets().model_id().into(), source.clone());
        let factory = factory(catalog, prepared, root.path());
        let encoder = factory.context().unwrap();
        assert!(encoder.tokenize("red", ContextInput::Query).is_err());
        assert!(!encoder.is_prepared().unwrap());
        copy_tree(
            &fixtures().join("context/valid").join("b".repeat(40)),
            &source,
        );
        assert_eq!(
            encoder.tokenize("red", ContextInput::Query).unwrap().ids,
            [4, 1, 2, 5]
        );
        fs::remove_dir_all(&source).unwrap();
        let vector = encoder.embed_query("red").unwrap();
        assert_eq!(&vector[..2], &[12., 4.]);
        assert_eq!(vector.len(), 768);
        assert!(encoder.is_prepared().unwrap());
    }

    #[test]
    fn deferred_reranker_uses_native_preparation_and_owns_its_published_graph() {
        let root = tempfile::tempdir().unwrap();
        let fixture = fixtures().join("ettin");
        let manifest: Value =
            serde_json::from_slice(&fs::read(fixture.join("manifest.json")).unwrap()).unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.reranker =
            RerankerModel::from_json(&manifest["head"]["definition"].to_string()).unwrap();
        let source = root
            .path()
            .join(catalog.reranker.source_assets().revision());
        copy_tree(
            &fixture.join(manifest["head"]["source"].as_str().unwrap()),
            &source,
        );
        let runtime = onnx();
        let direct = crate::OnnxReranker::new(
            catalog.reranker.clone(),
            None,
            Some(source.clone()),
            root.path().join("direct"),
            runtime.clone(),
            crate::RerankOptions::default(),
        )
        .unwrap();
        let expected = direct.score("x", &["y", "x x x"]).unwrap().scores;
        let mut prepared = resources(root.path());
        prepared.onnx = Some(runtime);
        prepared.source_overrides.insert(
            catalog.reranker.source_assets().model_id().into(),
            source.clone(),
        );
        let factory = factory(catalog, prepared, root.path());
        let reranker = factory.reranker().unwrap();
        assert!(!reranker.is_prepared().unwrap());
        assert_eq!(
            reranker.score("x", &["y", "x x x"]).unwrap().scores,
            expected
        );
        fs::remove_dir_all(source).unwrap();
        assert_eq!(
            reranker.score("x", &["y", "x x x"]).unwrap().scores,
            expected
        );
    }

    #[test]
    fn factory_rejects_wrong_native_module_and_core_then_retries_the_same_encoder_after_repair() {
        use serde_json::json;
        use sha2::{Digest, Sha256};
        let (root, model, source, _) = crate::transformer_test_support::fixture();
        let module = PathBuf::from(std::env::var_os("KEN_TORCH_MODULE").unwrap());
        let bytes = fs::read(module).unwrap();
        let local_module = root.path().join("repaired-module");
        fs::write(&local_module, b"wrong native code").unwrap();
        let preparation: Value = serde_json::from_slice(
            &fs::read(PathBuf::from(
                std::env::var_os("KEN_TORCH_PREPARATION").unwrap(),
            ))
            .unwrap(),
        )
        .unwrap();
        let libraries: BTreeMap<_, _> = preparation["libraries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| {
                (
                    format!("lib/{}", row["name"].as_str().unwrap()),
                    json!({"bytes":row["bytes"],"sha256":row["sha256"]}),
                )
            })
            .collect();
        let core = root.path().join("borrowed-core");
        fs::create_dir_all(core.join("lib")).unwrap();
        let original_core = PathBuf::from(std::env::var_os("KEN_TORCH_CORE").unwrap());
        let broken = libraries.keys().next().unwrap().clone();
        for name in libraries.keys() {
            if name == &broken {
                fs::write(core.join(name), b"wrong core").unwrap();
            } else {
                std::os::unix::fs::symlink(original_core.join(name), core.join(name)).unwrap();
            }
        }
        let runtime = crate::NativeTransformerRuntime::from_json(&json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{
            "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"2.9.0",
            "module":{"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))},"libraries":libraries
        }]}).to_string(), &local_module, &core).unwrap();
        let spec = EncoderSpec {
            model_id: model.assets().model_id().into(),
            revision: model.assets().revision().into(),
            backend: EncoderBackend::SentenceTransformers,
            dtype: TransformerDtype::Float32,
            sequence_length: 16,
            batch_size: 4,
        };
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.transformers = vec![model];
        let mut prepared = resources(root.path());
        prepared.torch = Some(runtime.clone());
        prepared.transformer_device = TransformerDeviceRequest::Cpu;
        prepared
            .source_overrides
            .insert(spec.model_id.clone(), source.snapshot().into());
        let factory = factory(catalog, prepared, root.path());
        let encoder = factory.encoder(&spec, &legacy("macos-torch.json")).unwrap();
        let error = encoder.embed_query("red").unwrap_err().to_string();
        assert!(error.contains("artifact size mismatch"), "{error}");
        assert!(!encoder.is_prepared().unwrap());
        assert!(runtime.loaded_identity().unwrap().is_none());
        fs::write(local_module, bytes).unwrap();
        assert!(
            encoder
                .embed_query("red")
                .unwrap_err()
                .to_string()
                .contains("artifact size mismatch")
        );
        assert!(!encoder.is_prepared().unwrap());
        assert!(runtime.loaded_identity().unwrap().is_none());
        fs::remove_file(core.join(&broken)).unwrap();
        std::os::unix::fs::symlink(original_core.join(&broken), core.join(&broken)).unwrap();
        let actual = encoder.embed_query("red").unwrap();
        assert_eq!(actual.len(), 4);
        assert!(encoder.is_prepared().unwrap());
        assert_eq!(encoder.family(), EncoderFamily::SentenceTransformer);
        assert_eq!(encoder.embed_query("red").unwrap(), actual);
    }

    #[test]
    fn deferred_judge_preserves_actual_empty_loading_and_owned_score_policy() {
        use serde_json::json;
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut config: Value = serde_json::from_slice(
            &fs::read(repo.join("native/ken-torch-backend/tests/fixtures/qwen/config.json"))
                .unwrap(),
        )
        .unwrap();
        config["max_position_embeddings"] = json!(512);
        let mut tokenizer: Value = serde_json::from_slice(
            &fs::read(
                fixtures()
                    .join("context/valid")
                    .join("b".repeat(40))
                    .join("tokenizer.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let vocab = tokenizer["model"]["vocab"].as_object_mut().unwrap();
        vocab.remove("find");
        vocab.remove("red");
        vocab.insert("yes".into(), json!(1));
        vocab.insert("no".into(), json!(2));
        let (root, model, source, runtime) = crate::transformer_test_support::fixture_with_details(
            &[("config.json", config)],
            None,
            "judge",
            Some(&tokenizer),
        );
        let spec = EncoderSpec {
            model_id: model.assets().model_id().into(),
            revision: model.assets().revision().into(),
            backend: EncoderBackend::SentenceTransformers,
            dtype: TransformerDtype::Float32,
            sequence_length: 128,
            batch_size: 1,
        };
        let direct = crate::RelevanceJudge::new(
            model.clone(),
            source.clone(),
            runtime.clone(),
            TransformerSettings {
                dtype: Some(spec.dtype),
                sequence_length: Some(128),
                batch_size: Some(1),
            },
            TransformerDeviceRequest::Cpu,
        )
        .unwrap();
        let expected = direct
            .score("red", &["red", "find"], "implementation")
            .unwrap();
        let mut catalog = ModelCatalog::built_in().unwrap();
        catalog.transformers = vec![model];
        let mut prepared = resources(root.path());
        prepared.torch = Some(runtime);
        prepared.transformer_device = TransformerDeviceRequest::Cpu;
        prepared
            .source_overrides
            .insert(spec.model_id.clone(), source.snapshot().into());
        let factory = factory(catalog, prepared, root.path());
        let judge = factory.judge(&spec, &legacy("macos-torch.json")).unwrap();
        assert!(judge.preparation().unwrap().is_none());
        assert!(judge.score("", &[], "implementation").is_err());
        assert!(judge.preparation().unwrap().is_some());
        fs::remove_dir_all(source.snapshot()).unwrap();
        assert_eq!(
            judge
                .score("red", &["red", "find"], "implementation")
                .unwrap(),
            expected
        );
    }

    #[test]
    fn deferred_expansion_prepares_real_ct2_only_for_translation() {
        let root = tempfile::tempdir().unwrap();
        let catalog = ModelCatalog::built_in().unwrap();
        let mut prepared = resources(root.path());
        let source = PathBuf::from(
            std::env::var_os("KEN_TRANSLATION_SOURCE").expect("prepare actual CT2 source"),
        );
        prepared.source_overrides.insert(
            catalog.translation.source_assets().model_id().into(),
            source.clone(),
        );
        let direct = crate::LocalQueryExpansion::new(
            catalog.translation.clone(),
            Some(source),
            catalog.translation.cache_path(&root.path().join("direct")),
        )
        .unwrap();
        let direct = if let Some((registration, module, core)) =
            crate::query_expansion::oracle::native_declaration()
        {
            let runtime =
                crate::NativeTranslationRuntime::from_json(&registration, &module, &core).unwrap();
            prepared.translation = Some(runtime.clone());
            direct.with_native_runtime(runtime)
        } else {
            direct
        };
        let query = "¿Dónde está la función que elimina archivos?";
        let expected = direct.expand_detailed(query).unwrap();
        let factory = factory(catalog, prepared, root.path());
        let expansion = factory.expansion().unwrap();
        assert_eq!(
            expansion.expand("find the input parser").unwrap(),
            "find the input parser"
        );
        assert!(!expansion.is_loaded());
        let actual = expansion.expand_detailed(query).unwrap();
        assert_eq!(actual.text, expected.text);
        assert_eq!(
            serde_json::to_value(actual.trace).unwrap(),
            serde_json::to_value(expected.trace).unwrap()
        );
        assert!(expansion.is_loaded());
        assert!(expansion.runtime_identity().unwrap().is_some());
    }
}
