//! Serialized request state. Scoring, delivery and productivity stay in domains.
use crate::{Error, Result, hooks};
use ken_context::{
    BriefOptions, Clock, ContextNumerics, Policy, RankRequest, RankResult, RenderOptions,
};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::query_encoder::QueryEncoder;
use ken_store::ProjectStore;
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    rc::Rc,
    time::{Instant, SystemTime, UNIX_EPOCH},
};
struct Session {
    agent: String,
    pk: i64,
    iteration: i64,
    anchor: Option<i64>,
    cached: Option<RankResult>,
    prompt: String,
    seen: BTreeMap<String, String>,
}
pub struct DaemonState {
    paths: ProjectPaths,
    store: ProjectStore,
    encoder: Rc<dyn QueryEncoder>,
    numerics: Box<dyn ContextNumerics>,
    policy: Policy,
    sessions: Vec<Session>,
    pub(crate) auth_token: String,
    pub(crate) project_id: String,
    pub(crate) started: Instant,
    pub(crate) last_activity: Instant,
    pub(crate) empty_since: Option<Instant>,
    checks: Option<ken_checks_application::SchedulerHost>,
    checks_app: Option<ken_checks_application::ChecksApplication>,
    pub(crate) brief_upgrade: Option<(String, String)>,
    pub(crate) brief_reembed: Option<String>,
}
fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}
fn clock() -> Clock {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    Clock {
        now_ms: now.as_millis().min(i64::MAX as u128) as i64,
        now_ns: now.as_nanos().min(i64::MAX as u128) as i64,
    }
}
fn required<'a>(body: &'a Value, key: &str) -> Result<&'a str> {
    body.get(key)
        .ok_or_else(|| Error::Missing(key.into()))?
        .as_str()
        .ok_or_else(|| Error::Invalid(format!("{key} must be a string")))
}
fn string(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        v => v.to_string(),
    }
}
fn positive(value: &Value) -> Option<i64> {
    value
        .as_i64()
        .or_else(|| value.as_str().and_then(|s| s.trim().parse().ok()))
        .filter(|n| *n > 0)
}
impl DaemonState {
    pub fn open(
        root: &Path,
        encoder: Rc<dyn QueryEncoder>,
        numerics: Box<dyn ContextNumerics>,
        policy: Policy,
    ) -> Result<Self> {
        let root = root.canonicalize()?;
        let context = DiscoveryContext {
            cwd: root.clone(),
            home: None,
            forced_root: None,
        };
        let paths = ProjectPaths::at(&root, &context).map_err(crate::invalid)?;
        let meta: Value = serde_json::from_slice(&std::fs::read(paths.meta())?)?;
        let auth_token = meta["auth_token"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| Error::Invalid("project auth_token must be a nonempty string".into()))?
            .to_owned();
        let project_id = meta
            .get("project_id")
            .map(string)
            .unwrap_or_else(|| "?".into());
        let mut store = ProjectStore::open(&paths)?;
        store.initialize()?;
        store
            .database()
            .set_meta("ken_version", env!("CARGO_PKG_VERSION"))?;
        Ok(Self {
            paths,
            store,
            encoder,
            numerics,
            policy,
            sessions: Vec::new(),
            auth_token,
            project_id,
            started: Instant::now(),
            last_activity: Instant::now(),
            empty_since: None,
            checks: None,
            checks_app: None,
            brief_upgrade: None,
            brief_reembed: None,
        })
    }
    pub fn connection(&self) -> &Connection {
        self.store.database().connection()
    }
    pub fn active_sessions(&self) -> usize {
        self.sessions.len()
    }
    pub fn paths(&self) -> &ProjectPaths {
        &self.paths
    }
    pub fn attach_checks(
        &mut self,
        application: ken_checks_application::ChecksApplication,
    ) -> Result<()> {
        let host =
            ken_checks_application::SchedulerHost::spawn(application.clone(), Default::default())?;
        self.checks = Some(host);
        self.checks_app = Some(application);
        Ok(())
    }
    fn touch(&mut self) {
        self.last_activity = Instant::now();
    }
    fn start(&mut self, agent: &str) -> Result<i64> {
        if let Some(session) = self.sessions.iter().find(|s| s.agent == agent) {
            return Ok(session.pk);
        }
        self.connection().execute(
            "INSERT INTO cr_sessions(agent_id,started_at) VALUES(?,?)",
            params![agent, now_ms()],
        )?;
        let pk = self.connection().last_insert_rowid();
        self.sessions.push(Session {
            agent: agent.into(),
            pk,
            iteration: 0,
            anchor: None,
            cached: None,
            prompt: String::new(),
            seen: BTreeMap::new(),
        });
        self.empty_since = None;
        self.touch();
        Ok(pk)
    }
    fn next(&mut self, agent: &str) -> Result<(i64, i64, Option<i64>)> {
        self.start(agent)?;
        let session = self
            .sessions
            .iter_mut()
            .find(|s| s.agent == agent)
            .expect("created session");
        session.iteration += 1;
        let result = (session.pk, session.iteration, session.anchor);
        self.touch();
        Ok(result)
    }
    fn record_context(
        &mut self,
        agent: &str,
        kind: &str,
        content: &str,
        embedding: Option<&[f32]>,
    ) -> Result<i64> {
        let (pk, iteration, _) = self.next(agent)?;
        let blob = embedding.map(|v| v.iter().flat_map(|f| f.to_le_bytes()).collect::<Vec<_>>());
        self.connection().execute("INSERT INTO cr_contexts(session_id,kind,content,iteration,embedding,created_at) VALUES(?,?,?,?,?,?)",params![pk,kind,content,iteration,blob,now_ms()])?;
        let id = self.connection().last_insert_rowid();
        if kind == "user_prompt"
            && let Some(session) = self.sessions.iter_mut().find(|s| s.agent == agent)
        {
            session.anchor = Some(id);
        }
        self.touch();
        Ok(id)
    }
    fn interaction(&mut self, agent: &str, event: &str, path: &str) -> Result<()> {
        let (pk, iteration, anchor) = self.next(agent)?;
        self.connection().execute("INSERT INTO cr_interactions(session_id,context_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(?,?,?,?,'file',?,1.,?)",params![pk,anchor,iteration,event,path,now_ms()])?;
        self.touch();
        Ok(())
    }
    fn end(&mut self, agent: &str) -> Result<()> {
        let iteration = self
            .sessions
            .iter()
            .find(|s| s.agent == agent)
            .map_or(0, |s| s.iteration);
        if let Err(error) =
            ken_context::snapshot_session_scores(self.connection(), agent, iteration, now_ms())
        {
            eprintln!("ken session snapshot failed: {error}");
        }
        self.connection().execute(
            "UPDATE cr_sessions SET ended_at=? WHERE agent_id=? AND ended_at IS NULL",
            params![now_ms(), agent],
        )?;
        self.sessions.retain(|s| s.agent != agent);
        if self.sessions.is_empty() {
            self.empty_since = Some(Instant::now());
        }
        self.touch();
        Ok(())
    }
    pub(crate) fn close_checks(&mut self) -> Result<()> {
        if let Some(host) = &mut self.checks {
            host.close()?;
        }
        Ok(())
    }
    pub fn finalize(&mut self) -> Result<()> {
        self.close_checks()?;
        let agents = self
            .sessions
            .iter()
            .map(|s| s.agent.clone())
            .collect::<Vec<_>>();
        let mut first = None;
        for agent in agents {
            if let Err(error) = self.end(&agent)
                && first.is_none()
            {
                first = Some(error);
            }
        }
        first.map_or(Ok(()), Err)
    }
    pub fn handle(&mut self, path: &str, body: Value) -> Result<Value> {
        match path {
            "/sessions/start" => {
                let agent = required(&body, "session_id")?;
                let pk = self.start(agent)?;
                let recent = ken_knowledge::findings::list(
                    self.connection(),
                    3,
                    None,
                    Some(self.paths.root()),
                    &[],
                )
                .unwrap_or_default();
                let checks = self.check_observations(&recent);
                let options = BriefOptions {
                    checks,
                    now_ms: now_ms(),
                    project_root: Some(self.paths.root().into()),
                    model_upgrade: self.brief_upgrade.clone(),
                    reembed_reason: self.brief_reembed.clone(),
                };
                let mut block = ken_context::build_session_brief(self.connection(), &options)
                    .ok()
                    .and_then(|s| s.to_utf8())
                    .unwrap_or_default();
                if let Some(app) = &self.checks_app {
                    match app.resume() {
                        Ok(notice) if !notice.is_empty() => {
                            block.push('\n');
                            block.push_str(&notice)
                        }
                        Err(e) => eprintln!("ken check resume failed: {e}"),
                        _ => (),
                    }
                }
                Ok(json!({"ok":true,"ken_session_pk":pk,"context_block":block}))
            }
            "/sessions/end" => {
                self.end(required(&body, "session_id")?)?;
                Ok(json!({"ok":true}))
            }
            "/prompts" => {
                let agent = required(&body, "session_id")?;
                let content = body.get("prompt").map(string).unwrap_or_default();
                let mut block = self.prompt(agent, &content)?;
                if let Some(host) = &self.checks {
                    let notice = host.drain(agent);
                    if !notice.is_empty() {
                        if block.chars().count() + notice.chars().count() < 3500 {
                            block.push('\n');
                            block.push_str(&notice);
                        } else {
                            block = notice;
                        }
                    }
                }
                Ok(json!({"ok":true,"context_block":block}))
            }
            "/tools/pre" => {
                let agent = required(&body, "session_id")?;
                let tool = body
                    .get("tool")
                    .or_else(|| body.get("tool_name"))
                    .map(string)
                    .unwrap_or_default();
                let input = body
                    .get("input")
                    .filter(|v| hooks::truth(v))
                    .or_else(|| body.get("tool_input"))
                    .unwrap_or(&Value::Null);
                let event = hooks::classify_tool(&tool, input);
                self.record_context(
                    agent,
                    "tool_call_pre",
                    &json!({"tool":tool,"target":event.target}).to_string(),
                    None,
                )?;
                if let Some(target) = event.target {
                    self.interaction(agent, &event.event, &target)?;
                }
                Ok(json!({"ok":true}))
            }
            "/tools/post" => {
                let agent = required(&body, "session_id")?;
                let tool = body
                    .get("tool")
                    .or_else(|| body.get("tool_name"))
                    .map(string)
                    .unwrap_or_default();
                let success = body.get("success").map(hooks::truth).unwrap_or(true);
                self.record_context(
                    agent,
                    "tool_call_post",
                    &json!({"tool":tool,"success":success}).to_string(),
                    None,
                )?;
                let input = body
                    .get("input")
                    .filter(|v| hooks::truth(v))
                    .or_else(|| body.get("tool_input"))
                    .unwrap_or(&Value::Null);
                let event = hooks::classify_tool(&tool, input);
                if !success {
                    if let Some(target) = event.target
                        && let Some(session) = self.sessions.iter().find(|s| s.agent == agent)
                    {
                        self.connection().execute("DELETE FROM cr_interactions WHERE id=(SELECT id FROM cr_interactions WHERE session_id=? AND target_path=? ORDER BY id DESC LIMIT 1)",params![session.pk,target])?;
                        self.touch();
                    }
                } else if event.event == "edit"
                    && let Some(host) = &self.checks
                {
                    let paths = self.edited_paths(input, event.target.as_deref());
                    if let Err(e) = host.enqueue(agent, &paths) {
                        eprintln!("ken check scheduling failed: {e}");
                    }
                }
                Ok(json!({"ok":true}))
            }
            "/turn-end" => {
                let agent = required(&body, "session_id")?;
                let content = body
                    .get("assistant_text")
                    .filter(|v| hooks::truth(v))
                    .map(string)
                    .unwrap_or_default();
                let stored = content.chars().take(8000).collect::<String>();
                self.record_context(agent, "turn_end", &stored, None)?;
                for path in self.cited_paths(&content)? {
                    self.interaction(agent, "cited", &path)?;
                }
                if let Some(host) = &self.checks
                    && let Err(e) = host.enqueue(agent, &[])
                {
                    eprintln!("ken check scheduling failed: {e}");
                }
                Ok(json!({"ok":true}))
            }
            "/interactions/dismiss" => {
                let Some(target) = body["target"]
                    .as_str()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                else {
                    return Ok(json!({"ok":true}));
                };
                if let Some(agent) = self.sessions.last().map(|s| s.agent.clone()) {
                    self.interaction(&agent, "dismissed", target)?;
                    if let Some(reason) = body.get("reason").filter(|v| hooks::truth(v)) {
                        self.record_context(
                            &agent,
                            "dismiss_reason",
                            &format!("{target}: {}", string(reason)),
                            None,
                        )?;
                    }
                }
                Ok(json!({"ok":true}))
            }
            "/rank" => self.manual_rank(&body, false),
            "/explain" => self.manual_rank(&body, true),
            "/file/symbols" => {
                let path = required(&body, "path")?;
                let navigation = ken_search::navigation::IndexNavigation::open(&self.paths)
                    .map_err(crate::invalid)?;
                let doc = navigation
                    .file_symbols(
                        path,
                        body.get("include_docstrings")
                            .map(hooks::truth)
                            .unwrap_or(true),
                    )
                    .map_err(crate::invalid)?;
                self.touch();
                Ok(serde_json::to_value(doc)?)
            }
            "/symbol/detail" => {
                let navigation = ken_search::navigation::IndexNavigation::open(&self.paths)
                    .map_err(crate::invalid)?;
                let doc = navigation
                    .symbol_detail(
                        required(&body, "path")?,
                        required(&body, "qualname")?,
                        body.get("include_snippet")
                            .map(hooks::truth)
                            .unwrap_or(true),
                    )
                    .map_err(crate::invalid)?;
                self.touch();
                Ok(serde_json::to_value(doc)?)
            }
            "/references" => {
                let doc = ken_search::text_search::WorktreeTextSearch::new(self.paths.clone())
                    .find(
                        required(&body, "query")?,
                        body.get("mode")
                            .and_then(Value::as_str)
                            .unwrap_or("literal")
                            == "literal",
                        body["language"].as_str().unwrap_or(""),
                        positive(&body["limit"]).unwrap_or(50),
                    )
                    .map_err(crate::invalid)?;
                self.touch();
                Ok(serde_json::to_value(doc)?)
            }
            "/shutdown" => Ok(json!({"ok":true})),
            _ => Err(Error::NotFound),
        }
    }
    fn request(
        &self,
        agent: String,
        iteration: i64,
        prompt: &str,
        embedding: Vec<f32>,
        reactive: bool,
    ) -> RankRequest {
        RankRequest {
            agent_id: agent,
            current_iteration: iteration,
            prompt: prompt.into(),
            prompt_embedding: embedding,
            project_root: Some(self.paths.root().into()),
            include_reactive: reactive,
            clock: clock(),
            ..Default::default()
        }
    }
    fn prompt(&mut self, agent: &str, content: &str) -> Result<String> {
        if content.chars().all(ken_text::unicode::whitespace) {
            self.record_context(agent, "user_prompt", content, None)?;
            return Ok(String::new());
        }
        let vector = match self.encoder.embed_query(&content.into()) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("ken prompt embedding failed: {e}");
                self.record_context(agent, "user_prompt", content, None)?;
                return Ok(String::new());
            }
        };
        self.record_context(agent, "user_prompt", content, Some(&vector))?;
        let iteration = self
            .sessions
            .iter()
            .find(|s| s.agent == agent)
            .map_or(0, |s| s.iteration);
        let request = self.request(agent.into(), iteration, content, vector, true);
        let result = match ken_context::rank(
            self.store.database().connection(),
            &request,
            &self.policy,
            self.numerics.as_mut(),
        ) {
            Ok(result) => result,
            Err(e) => {
                eprintln!("ken ranker failed: {e}");
                return Ok(String::new());
            }
        };
        let topics = result
            .findings
            .iter()
            .filter_map(|f| f.topic.to_utf8())
            .collect::<Vec<_>>();
        let initial = ken_knowledge::records::for_topics(
            self.connection(),
            &topics,
            Some(self.paths.root()),
            &[],
        )
        .unwrap_or_default();
        let checks = self.check_observations(&initial);
        let memories = ken_knowledge::records::enrich(
            self.connection(),
            &initial,
            Some(self.paths.root()),
            &checks,
        )
        .unwrap_or(initial);
        let session = self.sessions.iter_mut().find(|s| s.agent == agent);
        let knowledge = if let Some(session) = session {
            session.cached = Some(result.clone());
            session.prompt = content.into();
            ken_knowledge::context::render_brief(&memories, 1100, &mut session.seen)
        } else {
            String::new()
        };
        let remaining =
            3500i64 - knowledge.chars().count() as i64 - i64::from(!knowledge.is_empty());
        let options = RenderOptions {
            checks,
            verbose: 0,
            max_chars: Some(remaining),
            project_root: Some(self.paths.root().into()),
        };
        let mut block = ken_context::render_block(self.connection(), &result, &options)?
            .to_utf8()
            .unwrap_or_default();
        if !knowledge.is_empty() {
            block.push('\n');
            block.push_str(&knowledge);
        }
        Ok(block)
    }
    fn manual_rank(&mut self, body: &Value, explain: bool) -> Result<Value> {
        let mut query = body
            .get("query")
            .filter(|v| hooks::truth(v))
            .map(string)
            .unwrap_or_default()
            .trim_matches(ken_text::unicode::whitespace)
            .to_owned();
        let explicit = !query.is_empty();
        let (mut agent, mut iteration, cached, prompt) = self
            .sessions
            .last()
            .map(|s| {
                (
                    s.agent.clone(),
                    s.iteration,
                    s.cached.clone(),
                    s.prompt.clone(),
                )
            })
            .unwrap_or_else(|| ("__ken_mcp__".into(), 0, None, String::new()));
        let verbose = body
            .get("verbose")
            .and_then(|v| {
                v.as_i64()
                    .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
            })
            .unwrap_or(1)
            .clamp(0, 2);
        let max_chars = positive(&body["max_chars"]);
        if query.is_empty()
            && !explain
            && let Some(result) = cached
        {
            return self.rank_response(&result, &prompt, verbose, max_chars);
        }
        if query.is_empty() {
            query = prompt;
            if query.is_empty() {
                let latest = self.connection().query_row(
                "SELECT s.agent_id,c.content,c.iteration FROM cr_contexts c JOIN cr_sessions s ON s.id=c.session_id WHERE c.kind='user_prompt' AND c.content<>'' ORDER BY c.created_at DESC,c.id DESC LIMIT 1",
                [], |r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?))
            ).optional()?;
                if let Some((a, p, i)) = latest {
                    agent = a;
                    query = p;
                    iteration = i;
                } else {
                    return Ok(
                        json!({"ok":false,"error":"no cached prompt — submit one or pass query"}),
                    );
                }
            }
        }
        let vector = match self.encoder.embed_query(&query.clone().into()) {
            Ok(vector) => vector,
            Err(error) => {
                eprintln!("ken query embedding failed: {error}");
                return Ok(json!({"ok":false,"error":"embedder failed"}));
            }
        };
        let request = self.request(agent, iteration, &query, vector, explain && !explicit);
        if explain {
            match ken_context::explain(
                self.store.database().connection(),
                &request,
                &self.policy,
                self.numerics.as_mut(),
                10,
            ) {
                Ok(result) => {
                    let mut value = serde_json::to_value(result)?;
                    value["ok"] = json!(true);
                    Ok(value)
                }
                Err(error) => {
                    eprintln!("ken explain failed: {error}");
                    Ok(json!({"ok":false,"error":"explain failed"}))
                }
            }
        } else {
            match ken_context::rank(
                self.store.database().connection(),
                &request,
                &self.policy,
                self.numerics.as_mut(),
            ) {
                Ok(result) => self.rank_response(&result, &query, verbose, max_chars),
                Err(error) => {
                    eprintln!("ken rank failed: {error}");
                    Ok(json!({"ok":false,"error":"ranker failed"}))
                }
            }
        }
    }
    fn rank_response(
        &self,
        result: &RankResult,
        prompt: &str,
        verbose: i64,
        max_chars: Option<i64>,
    ) -> Result<Value> {
        let topics = result
            .findings
            .iter()
            .filter_map(|f| f.topic.to_utf8())
            .collect::<Vec<_>>();
        let hits = ken_knowledge::records::for_topics(
            self.connection(),
            &topics,
            Some(self.paths.root()),
            &[],
        )
        .unwrap_or_default();
        let checks = self.check_observations(&hits);
        let options = RenderOptions {
            checks,
            verbose,
            max_chars,
            project_root: Some(self.paths.root().into()),
        };
        let block = ken_context::render_block(self.connection(), result, &options)?
            .to_utf8()
            .unwrap_or_default();
        let chars = block.chars().count();
        Ok(
            json!({"ok":true,"context_block":block,"prompt":prompt,"files":result.files.len(),"symbols":result.symbols.len(),"findings":result.findings.len(),"context_chars":chars,"context_est_tokens":chars.div_ceil(4)}),
        )
    }
    fn cited_paths(&self, text: &str) -> Result<Vec<String>> {
        let mut hits = BTreeSet::new();
        for candidate in ken_context::channels::source_path_mentions(&text.into())
            .into_iter()
            .collect::<BTreeSet<_>>()
        {
            if candidate.contains('/') {
                if self.connection().query_row(
                    "SELECT EXISTS(SELECT 1 FROM ci_files WHERE path=?)",
                    [&candidate],
                    |r| r.get::<_, bool>(0),
                )? {
                    hits.insert(candidate);
                }
            } else {
                let mut statement = self
                    .connection()
                    .prepare("SELECT path FROM ci_files WHERE path LIKE ? LIMIT 2")?;
                let paths = statement
                    .query_map([format!("%/{candidate}")], |r| r.get::<_, String>(0))?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                if paths.len() == 1 {
                    hits.insert(paths[0].clone());
                }
            }
        }
        Ok(hits.into_iter().collect())
    }
    fn check_observations(&self, hits: &[Value]) -> Vec<ken_knowledge::records::CheckObservation> {
        let Some(app) = &self.checks_app else {
            return Vec::new();
        };
        let Ok(store) = ken_contracts::checks::Store::new(self.paths.root()) else {
            return Vec::new();
        };
        let runs = hits
            .iter()
            .flat_map(|hit| {
                hit["justification"]["check_runs"]
                    .as_array()
                    .into_iter()
                    .flatten()
            })
            .filter_map(Value::as_str)
            .collect::<BTreeSet<_>>();
        runs.into_iter()
            .filter_map(|run| {
                let receipt = store.read_receipt(run).ok()?;
                let validity = app.freshness(run, std::time::Duration::from_secs(2)).ok()?;
                Some(ken_knowledge::records::CheckObservation {
                    run_id: run.into(),
                    receipt_path: format!(".ken/checks/runs/{run}.json"),
                    status: receipt.status,
                    rules: receipt
                        .checks
                        .iter()
                        .map(|check| check.rule.clone())
                        .collect(),
                    observations: validity["checks"].clone(),
                    validity,
                })
            })
            .collect()
    }
    fn edited_paths(&self, input: &Value, target: Option<&str>) -> Vec<String> {
        ken_contracts::checks::edited_paths(self.paths.root(), input, target)
    }
}
