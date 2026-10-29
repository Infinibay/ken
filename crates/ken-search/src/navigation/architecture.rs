//! Coverage-aware, bounded architecture reports over resolved indexed imports.
use super::{
    IndexNavigation, Result,
    graph::{self, Graph},
};
use ken_core::tool_output::Document;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

struct ImportTopology {
    paths: Vec<String>,
    edges: Graph,
    coverage: Document,
}
impl ImportTopology {
    fn load(nav: &IndexNavigation) -> Result<Self> {
        let files = nav
            .conn
            .prepare("SELECT id,path FROM ci_files")?
            .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
            .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
        let mut edges = BTreeSet::new();
        let mut active = BTreeSet::new();
        let mut query = nav.conn.prepare(
            "SELECT from_file_id,to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL",
        )?;
        let mut rows = query.query([])?;
        while let Some(row) = rows.next()? {
            let a: i64 = row.get(0)?;
            let b: i64 = row.get(1)?;
            if a == b || !files.contains_key(&a) || !files.contains_key(&b) {
                continue;
            }
            active.extend([a, b]);
            edges.insert((a, b));
        }
        let index = active
            .into_iter()
            .enumerate()
            .map(|(i, id)| (id, i))
            .collect::<BTreeMap<_, _>>();
        let paths = index.keys().map(|id| files[id].clone()).collect::<Vec<_>>();
        let mut adjacency = vec![Vec::new(); paths.len()];
        for (a, b) in edges {
            adjacency[index[&a]].push(index[&b]);
        }
        let (resolved, gap, external, total): (i64, i64, i64, i64) = nav.conn.query_row("SELECT COALESCE(SUM(to_file_id IS NOT NULL),0),COALESCE(SUM(resolution='unresolved'),0),COALESCE(SUM(resolution='external'),0),COUNT(*) FROM ci_imports", [], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?;
        let pct = (resolved + gap > 0)
            .then(|| rounded(100.0 * resolved as f64 / (resolved + gap) as f64, 1));
        let coverage = doc!("resolved":resolved,"total":total,"internal_resolved":resolved,"internal_unresolved":gap,"internal_total":resolved+gap,"external":external,"internal_coverage_pct":pct);
        Ok(Self {
            paths,
            edges: adjacency,
            coverage,
        })
    }
    fn report(self, depth: i64, limit: i64) -> Document {
        if self.paths.is_empty() {
            return doc!("ok":true,"edge_coverage":self.coverage,"cycles":Vec::<Document>::new(),"layers":Vec::<Document>::new(),"clusters":Vec::<Document>::new(),"hubs":Vec::<Document>::new(),"sinks":Vec::<Document>::new(),"note":"no resolved import edges — graph queries unavailable");
        }
        let cap = limit.max(1) as usize;
        let detail = depth.max(1) as usize;
        let components = graph::strongly_connected(&self.edges);
        let mut cycles = components
            .iter()
            .filter(|c| c.len() > 1)
            .map(|c| {
                let mut paths = c.iter().map(|&v| self.paths[v].clone()).collect::<Vec<_>>();
                paths.sort();
                paths
            })
            .collect::<Vec<_>>();
        cycles.sort_by(|a, b| b.len().cmp(&a.len()).then_with(|| a[0].cmp(&b[0])));
        let cycle_count = cycles.len();
        let cycles = cycles
            .iter()
            .take(cap)
            .map(|paths| sample(paths, cap))
            .collect::<Vec<_>>();
        let levels = graph::condensation_layers(&self.edges, &components);
        let mut layers = BTreeMap::<usize, Vec<String>>::new();
        for (i, component) in components.iter().enumerate() {
            for &v in component {
                layers
                    .entry(levels[i])
                    .or_default()
                    .push(self.paths[v].clone());
            }
        }
        let layers = layers
            .into_iter()
            .enumerate()
            .map(|(rank, (layer, mut files))| {
                files.sort();
                let mut item = doc!("layer":layer,"size":files.len());
                if rank < detail {
                    item.insert("files", files.iter().take(cap).cloned().collect::<Vec<_>>());
                    if files.len() > cap {
                        item.insert("truncated", files.len() - cap);
                    }
                }
                item
            })
            .collect::<Vec<_>>();
        let undirected = graph::undirected(&self.edges);
        let groups = graph::communities(&undirected);
        let (pr, converged) = graph::pagerank(&self.edges);
        let (rpr, reverse_converged) = graph::pagerank(&graph::reverse(&self.edges));
        let modularity = graph::modularity(&groups, &undirected);
        let mut clusters = groups
            .into_iter()
            .filter(|c| c.len() >= 2)
            .collect::<Vec<_>>();
        clusters.sort_by(|a, b| {
            b.len()
                .cmp(&a.len())
                .then_with(|| self.paths[a[0]].cmp(&self.paths[b[0]]))
        });
        let cluster_count = clusters.len();
        let clusters = clusters.iter().take(cap).map(|members| {
            let mut paths = members.iter().map(|&v| self.paths[v].clone()).collect::<Vec<_>>();
            paths.sort();
            let central = members.iter().copied().fold(members[0], |best, v| if pr[v]>pr[best] { v } else { best });
            let mut item = doc!("label":common_dir(&paths),"size":members.len(),"central_file":self.paths[central].clone(),"members":paths.iter().take(cap).cloned().collect::<Vec<_>>());
            if members.len()>cap { item.insert("truncated",members.len()-cap); }
            item
        }).collect::<Vec<_>>();
        let top = |rank: &[f64], key| {
            let mut nodes = (0..self.paths.len()).collect::<Vec<_>>();
            nodes.sort_by(|&a, &b| rank[b].total_cmp(&rank[a]));
            nodes
                .into_iter()
                .take(cap)
                .map(|v| {
                    Document::object([
                        ("path", self.paths[v].clone().into()),
                        (key, rounded(rank[v], 5).into()),
                    ])
                })
                .collect::<Vec<_>>()
        };
        doc!("ok":true,"edge_coverage":self.coverage.clone(),"trust":"cycles are exact; layers/communities are approximate and degrade as unresolved imports rise",
            "quality":doc!("clusters_modularity":rounded(modularity,3),"clusters_meaningful":modularity>=0.3,"pagerank_converged":converged&&reverse_converged),
            "summary":doc!("graph_files":self.paths.len(),"cycles":cycle_count,"layers":layers.len(),"clusters":cluster_count,"note":format!("showing top {cap} of each list; layer file samples for the first {detail} layer(s) — raise limit/depth for more")),
            "cycles":cycles,"layers":layers,"clusters":clusters,"hubs":top(&pr,"pagerank"),"sinks":top(&rpr,"reverse_pagerank"))
    }
}
fn rounded(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}")
        .parse()
        .expect("finite graph score")
}
fn sample(files: &[String], cap: usize) -> Document {
    let mut value =
        doc!("size":files.len(),"files":files.iter().take(cap).cloned().collect::<Vec<_>>());
    if files.len() > cap {
        value.insert("truncated", files.len() - cap);
    }
    value
}
fn common_dir(paths: &[String]) -> String {
    let parents = paths
        .iter()
        .map(|p| {
            Path::new(p)
                .parent()
                .unwrap_or(Path::new(""))
                .to_string_lossy()
        })
        .map(|p| {
            if p.is_empty() {
                ".".into()
            } else {
                p.into_owned()
            }
        })
        .collect::<Vec<String>>();
    let mut common = parents.first().cloned().unwrap_or_default();
    for path in parents.iter().skip(1) {
        while !common.is_empty() && path != &common && !path.starts_with(&format!("{common}/")) {
            common = common
                .rsplit_once('/')
                .map_or("", |(prefix, _)| prefix)
                .into();
        }
    }
    if common.is_empty() {
        "(root)".into()
    } else {
        common
    }
}
impl IndexNavigation {
    pub fn architecture(&self, depth: i64, limit: i64) -> Result<Document> {
        Ok(ImportTopology::load(self)?.report(depth, limit))
    }
}
