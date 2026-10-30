use super::{
    InspectionSources, ObservationLog, Program, Result, identity, impact::result_uses,
    imports::ImportPlanner, invalid, queries,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
#[derive(Clone, Debug)]
pub enum ObservationKind {
    Definitions {
        name: Option<String>,
    },
    Neighbors {
        identities: Vec<String>,
        incoming: bool,
        outgoing: bool,
    },
    Targets {
        sites: Vec<String>,
        possible: bool,
    },
    Usages {
        sites: Vec<String>,
    },
}
impl ObservationKind {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Definitions { .. } => "definitions",
            Self::Neighbors { .. } => "calls",
            Self::Targets { possible, .. } => {
                if *possible {
                    "possible_targets"
                } else {
                    "targets"
                }
            }
            Self::Usages { .. } => "usages",
        }
    }
    fn query(&self) -> String {
        match self {
            Self::Definitions { name } => queries::definitions(name.as_deref()),
            Self::Neighbors {
                identities,
                incoming,
                outgoing,
            } => queries::neighbors(identities, *incoming, *outgoing),
            Self::Targets { sites, possible } => queries::targets(sites, *possible),
            Self::Usages { sites } => queries::usages(sites),
        }
    }
}
#[derive(Clone, Debug)]
pub struct ObservationRequest {
    pub root: PathBuf,
    pub query: String,
    pub scope: String,
    pub paths: Vec<String>,
    pub kind: ObservationKind,
    pub timeout_ms: f64,
    pub max_rows: usize,
    pub deadline: Instant,
}
pub trait InspectionQueries {
    fn identity(&self) -> String;
    fn observe(&mut self, request: &ObservationRequest) -> Result<Value>;
}
#[derive(Clone, Debug)]
pub struct ExploreRequest {
    pub path: String,
    pub targets: Vec<String>,
    pub relation: String,
    pub depth: usize,
    pub timeout_ms: f64,
    pub max_rows: usize,
}
struct Explorer<'a> {
    root: &'a Path,
    request: &'a ExploreRequest,
    deadline: Instant,
    total_deadline: Instant,
    queries: &'a mut dyn InspectionQueries,
    imports: ImportPlanner<'a>,
    log: ObservationLog,
    before: Value,
    version: String,
    paths: BTreeSet<String>,
    steps: Vec<Value>,
}
impl Explorer<'_> {
    fn remaining(&self) -> Result<Duration> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| invalid("inspection time budget exhausted"))
    }
    fn program(&self) -> Result<Program> {
        Program::from_batch(
            &self.request.path,
            &json!({"results":self.log.results,"snapshot":self.before}),
        )
    }
    fn observe(&mut self, kind: ObservationKind, paths: BTreeSet<String>) -> Result<Value> {
        let request = ObservationRequest {
            root: self.root.to_path_buf(),
            query: kind.query(),
            scope: self.request.path.clone(),
            paths: paths.into_iter().collect(),
            kind,
            timeout_ms: self.remaining()?.as_secs_f64() * 1000.,
            max_rows: self.request.max_rows,
            deadline: self.deadline,
        };
        let mut result = self.queries.observe(&request)?;
        if !result.is_object() {
            return Err(invalid(
                "native inspection query returned an invalid result",
            ));
        }
        if !result["analysis"]["manifest"].is_array() {
            result["complete"] = json!(false);
            result["reason"] = json!("query source manifest unavailable");
        }
        self.log.add(request.kind.name(), &request.query, &result)?;
        let expected = self.before["manifest"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|p| Some((p[0].as_str()?, p[1].as_str()?)))
            .collect::<std::collections::BTreeMap<_, _>>();
        if result["analysis"]["manifest"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|p| {
                p[0].as_str()
                    .zip(p[1].as_str())
                    .is_none_or(|(path, hash)| expected.get(path).copied() != Some(hash))
            })
        {
            self.log.fail("source_changed_during_inspection", true);
        }
        Ok(result)
    }
    fn locate(&mut self) -> Result<Vec<String>> {
        let files = self
            .request
            .targets
            .iter()
            .map(|t| t.split("::").next().unwrap_or(""))
            .collect::<BTreeSet<_>>();
        let mut selected = self
            .paths
            .iter()
            .filter(|p| {
                files.iter().any(|f| {
                    p.as_str() == *f || p.starts_with(&(f.trim_end_matches('/').to_owned() + "/"))
                })
            })
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut name = None;
        if self.request.targets.len() == 1 {
            let target = &self.request.targets[0];
            let (file, symbol) = target
                .split_once("::")
                .map_or((target.as_str(), None), |(p, s)| (p, Some(s)));
            if symbol.is_some() || selected.is_empty() {
                name = Some(
                    symbol
                        .unwrap_or(file)
                        .rsplit('.')
                        .next()
                        .unwrap_or("")
                        .to_owned(),
                );
            }
        }
        if selected.is_empty()
            && !self
                .request
                .targets
                .iter()
                .any(|t| t.contains("::") || t.contains('/'))
        {
            selected = self.paths.clone();
        }
        self.observe(ObservationKind::Definitions { name }, selected)?;
        let program = self.program()?;
        let mut seeds = Vec::new();
        let mut seen = BTreeSet::new();
        for target in &self.request.targets {
            for key in program.select(target) {
                if seen.insert(key.clone()) {
                    seeds.push(key);
                }
            }
        }
        Ok(seeds)
    }
    fn step(
        &mut self,
        frontier: &[String],
        incoming: bool,
        outgoing: bool,
        uses: bool,
    ) -> Result<()> {
        let program = self.program()?;
        let nodes = frontier
            .iter()
            .filter_map(|key| program.nodes.get(key))
            .cloned()
            .collect::<Vec<_>>();
        let paths = self.imports.neighbors(&nodes, incoming, outgoing)?;
        self.steps.push(json!({"symbols":frontier,"paths":paths}));
        let calls = self.observe(
            ObservationKind::Neighbors {
                identities: frontier.to_vec(),
                incoming,
                outgoing,
            },
            paths.clone(),
        )?;
        let sites = calls["rows"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|row| identity(&row[1]))
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        if !sites.is_empty() {
            self.observe(
                ObservationKind::Targets {
                    sites: sites.clone(),
                    possible: false,
                },
                paths.clone(),
            )?;
            self.observe(
                ObservationKind::Targets {
                    sites: sites.clone(),
                    possible: true,
                },
                paths.clone(),
            )?;
            if uses {
                self.observe(ObservationKind::Usages { sites }, paths)?;
            }
        }
        Ok(())
    }
    fn run(&mut self) -> Value {
        let mut frontier = Vec::new();
        let mut visited = BTreeSet::new();
        let work = (|| -> Result<()> {
            frontier = self.locate()?;
            if self.request.relation == "available" {
                frontier.clear();
            }
            for _ in 0..self.request.depth {
                if frontier.is_empty() {
                    break;
                }
                if frontier.len() > 100 {
                    self.log
                        .fail("inspection frontier exceeds 100 symbols", false);
                    break;
                }
                self.remaining()?;
                self.step(
                    &frontier,
                    self.request.relation != "outgoing",
                    ["roles", "outgoing"].contains(&self.request.relation.as_str()),
                    ["impact", "outgoing"].contains(&self.request.relation.as_str()),
                )?;
                if self.log.invalidated {
                    break;
                }
                visited.extend(frontier.iter().cloned());
                let program = self.program()?;
                let mut following = BTreeSet::new();
                match self.request.relation.as_str() {
                    "impact" => {
                        let current = frontier.iter().collect::<BTreeSet<_>>();
                        for call in &program.calls {
                            if call.resolution == "resolved"
                                && call.targets.iter().filter(|t| current.contains(t)).any(
                                    |target| {
                                        result_uses(&program, call, target)
                                            .iter()
                                            .any(|u| u["kind"] == "return")
                                    },
                                )
                            {
                                following.insert(call.owner.clone());
                            }
                        }
                    }
                    "outgoing" => {
                        for call in &program.calls {
                            if frontier.contains(&call.owner) {
                                following.extend(call.targets.iter().cloned());
                            }
                        }
                    }
                    _ => following = program.connected(&frontier, 1),
                }
                frontier = following
                    .difference(&visited)
                    .filter(|id| program.nodes.contains_key(*id))
                    .cloned()
                    .collect();
            }
            Ok(())
        })();
        if let Err(error) = work {
            self.log.fail(&error.to_string(), false);
        }
        let verification = (|| -> Result<()> {
            let budget = self
                .total_deadline
                .checked_duration_since(Instant::now())
                .filter(|d| !d.is_zero())
                .ok_or_else(|| invalid("inspection time budget exhausted"))?;
            let after = self.imports.capture(&self.request.path, budget)?;
            let expected = self.before["manifest"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|row| Some((row[0].as_str()?.to_owned(), row[1].as_str()?.to_owned())))
                .collect::<std::collections::BTreeMap<_, _>>();
            if after != self.before
                || self.version != self.queries.identity()
                || self
                    .log
                    .manifest
                    .iter()
                    .any(|(p, h)| expected.get(p) != Some(h))
            {
                self.log.fail("source_changed_during_inspection", true);
            }
            Ok(())
        })();
        if let Err(error) = verification {
            self.log.fail(&error.to_string(), false);
        }
        if !self.imports.issues.is_empty() {
            self.log.fail(
                "import discovery incomplete; supplied scope retained",
                false,
            );
        }
        let selection = json!({"basis":"requested identities and explicit imports, one frontier at a time","claim":"Statically modeled calls; computed imports/member names and runtime dispatch are not traced.","paths":self.log.paths,"issues":self.imports.issues,"steps":self.steps,"import_files_read":self.imports.edges.len(),"expanded_symbols":visited.len(),"depth_limited":!frontier.is_empty()});
        self.log.batch(&self.before, &self.version, &selection)
    }
}
pub fn explore(
    root: &Path,
    request: &ExploreRequest,
    queries: &mut dyn InspectionQueries,
    sources: &mut dyn InspectionSources,
) -> Result<Value> {
    if !request.timeout_ms.is_finite() || !(1.0..=120000.).contains(&request.timeout_ms) {
        return Err(invalid("timeout_ms must be 1..120000"));
    }
    let start = Instant::now();
    let total = Duration::from_secs_f64(request.timeout_ms / 1000.);
    let reserve = total.div_f64(10.).min(Duration::from_millis(500));
    let deadline = start
        .checked_add(total - reserve)
        .ok_or_else(|| invalid("inspection budget out of range"))?;
    let total_deadline = start
        .checked_add(total)
        .ok_or_else(|| invalid("inspection budget out of range"))?;
    let before = sources.capture(
        root,
        &request.path,
        deadline.saturating_duration_since(Instant::now()),
    )?;
    let paths = before["manifest"]
        .as_array()
        .ok_or_else(|| invalid("source inventory unavailable"))?
        .iter()
        .filter_map(|p| p[0].as_str().map(str::to_owned))
        .collect();
    let version = queries.identity();
    let imports = ImportPlanner::new(root, paths, sources, deadline)?;
    let paths = before["manifest"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|p| p[0].as_str().map(str::to_owned))
        .collect();
    let mut explorer = Explorer {
        root,
        request,
        deadline,
        total_deadline,
        queries,
        imports,
        log: ObservationLog::new(),
        before,
        version,
        paths,
        steps: Vec::new(),
    };
    Ok(explorer.run())
}
