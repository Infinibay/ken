//! Model names and prospective pins resolved from established project facts.
//! Storage adapters must establish vector absence before applying a fresh pin.
use crate::python_unicode;

pub const LEGACY_MODEL: &str = "sentence-transformers/all-MiniLM-L6-v2";
pub const RECOMMENDED_MODEL: &str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2";
pub const POTION_MODEL: &str = "minishlab/potion-code-16M-v2";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectModelFacts {
    /// None means missing/NULL; a present empty string still prevents a new pin.
    pub recorded_model: Option<String>,
    /// False must mean proven absence, never unreadable or unknown storage.
    pub file_vectors_present: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectModelResolution {
    pub model: String,
    pub initial_pin: Option<InitialModelPin>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InitialModelPin {
    pub model: String,
    pub document_space: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModelUpgrade {
    pub current: String,
    pub recommended: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ModelPrompts {
    pub query: &'static str,
    pub passage: &'static str,
}

/// An owned configuration snapshot; current process overrides are explicit inputs.
#[derive(Clone, Debug)]
pub struct ModelPolicy {
    recommended: String,
}

fn nonempty(value: Option<&str>) -> Option<&str> {
    value.filter(|value| !value.is_empty())
}

impl ModelPolicy {
    pub fn new(user_default: Option<&str>) -> Self {
        let recommended = user_default
            .filter(|value| value.chars().any(|c| !python_unicode::space(c)))
            .unwrap_or(POTION_MODEL)
            .to_owned();
        Self { recommended }
    }

    pub fn recommended_model(&self) -> &str {
        &self.recommended
    }

    fn project_model<'a>(
        &'a self,
        facts: &'a ProjectModelFacts,
        environment: Option<&'a str>,
    ) -> &'a str {
        nonempty(environment)
            .or_else(|| nonempty(facts.recorded_model.as_deref()))
            .unwrap_or_else(|| {
                if facts.file_vectors_present {
                    LEGACY_MODEL
                } else {
                    self.recommended_model()
                }
            })
    }

    pub fn resolve_project(
        &self,
        facts: &ProjectModelFacts,
        environment: Option<&str>,
    ) -> ProjectModelResolution {
        let model = self.project_model(facts, environment).to_owned();
        let initial_pin =
            (facts.recorded_model.is_none() && !facts.file_vectors_present).then(|| {
                InitialModelPin {
                    model: model.clone(),
                    document_space: 2,
                }
            });
        ProjectModelResolution { model, initial_pin }
    }

    pub fn active_model(
        &self,
        project: Option<&ProjectModelFacts>,
        environment: Option<&str>,
        forced: Option<&str>,
    ) -> String {
        nonempty(forced)
            .or_else(|| nonempty(environment))
            .unwrap_or_else(|| match project {
                Some(facts) => self.project_model(facts, environment),
                None => self.recommended_model(),
            })
            .to_owned()
    }

    pub fn pending_upgrade(
        &self,
        facts: &ProjectModelFacts,
        environment: Option<&str>,
    ) -> Option<ModelUpgrade> {
        if nonempty(environment).is_some() || self.project_model(facts, None) != LEGACY_MODEL {
            return None;
        }
        Some(ModelUpgrade {
            current: LEGACY_MODEL.into(),
            recommended: self.recommended.clone(),
        })
    }
}

pub fn prompts_for(model: &str) -> ModelPrompts {
    const QWEN: ModelPrompts = ModelPrompts {
        query: "Instruct: Given a developer's question, retrieve the code file that answers it\nQuery: ",
        passage: "",
    };
    const E5: ModelPrompts = ModelPrompts {
        query: "query: ",
        passage: "passage: ",
    };
    [
        ("Qwen/Qwen3-Embedding", QWEN),
        ("intfloat/multilingual-e5", E5),
        ("intfloat/e5", E5),
    ]
    .into_iter()
    .filter(|(prefix, _)| model.starts_with(prefix))
    .max_by_key(|(prefix, _)| prefix.len())
    .map_or(
        ModelPrompts {
            query: "",
            passage: "",
        },
        |(_, prompts)| prompts,
    )
}

pub fn is_asymmetric(model: &str) -> bool {
    let prompts = prompts_for(model);
    !prompts.query.is_empty() || !prompts.passage.is_empty()
}
