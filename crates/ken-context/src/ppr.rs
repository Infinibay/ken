//! Sparse three-step personalized propagation over typed file relationships.
use crate::{
    Policy, RankedItem, Result,
    boosts::{PathIndex, all_paths},
    prefix, text,
};
use rusqlite::{Connection, OptionalExtension};
use std::collections::{BTreeMap, BTreeSet};
fn link(
    edges: &mut Vec<((usize, usize), f64)>,
    indices: &mut BTreeMap<(usize, usize), usize>,
    by_path: &BTreeMap<&str, usize>,
    a: &str,
    b: &str,
    weight: f64,
) {
    let (Some(&a), Some(&b)) = (by_path.get(a), by_path.get(b)) else {
        return;
    };
    if a == b {
        return;
    }
    for pair in [(a, b), (b, a)] {
        let index = *indices.entry(pair).or_insert_with(|| {
            edges.push((pair, 0.));
            edges.len() - 1
        });
        edges[index].1 += weight;
    }
}
fn baskets(
    conn: &Connection,
    sql: &str,
    weight: f64,
    edges: &mut Vec<((usize, usize), f64)>,
    indices: &mut BTreeMap<(usize, usize), usize>,
    by_path: &BTreeMap<&str, usize>,
) -> Result<()> {
    let mut groups = Vec::<Vec<String>>::new();
    let mut positions = BTreeMap::new();
    let mut stmt = conn.prepare(sql)?;
    for row in stmt.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))? {
        let (group, path) = row?;
        let index = *positions.entry(group).or_insert_with(|| {
            groups.push(Vec::new());
            groups.len() - 1
        });
        if !groups[index].contains(&path) {
            groups[index].push(path);
        }
    }
    for group in groups {
        if !(2..=25).contains(&group.len()) {
            continue;
        }
        let weight = weight / (group.len() - 1) as f64;
        for a in 0..group.len() {
            for b in a + 1..group.len() {
                link(edges, indices, by_path, &group[a], &group[b], weight);
            }
        }
    }
    Ok(())
}
pub(crate) fn apply(conn: &Connection, files: &mut Vec<RankedItem>, policy: &Policy) -> Result<()> {
    if files.is_empty() {
        return Ok(());
    }
    let mut paths = all_paths(conn)?;
    paths.sort();
    if paths.len() < 2 {
        return Ok(());
    }
    let by_path = paths
        .iter()
        .enumerate()
        .map(|(i, p)| (p.as_str(), i))
        .collect::<BTreeMap<_, _>>();
    let (mut edges, mut indices) = (Vec::new(), BTreeMap::new());
    let mut statement=conn.prepare("SELECT src.path,dst.path FROM ci_imports i JOIN ci_files src ON src.id=i.from_file_id JOIN ci_files dst ON dst.id=i.to_file_id")?;
    for row in statement.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))? {
        let (a, b) = row?;
        link(&mut edges, &mut indices, &by_path, &a, &b, 1.);
    }
    let path_index = PathIndex::new(&paths);
    for path in &paths {
        for related in path_index.related(path) {
            link(&mut edges, &mut indices, &by_path, path, &related, 1.);
        }
    }
    baskets(
        conn,
        "SELECT session_id,target_path FROM cr_session_scores WHERE target_path IS NOT NULL AND score>0",
        0.7,
        &mut edges,
        &mut indices,
        &by_path,
    )?;
    if conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cr_commit_files'",
            [],
            |r| r.get::<_, i64>(0),
        )
        .optional()?
        .is_some()
    {
        baskets(
            conn,
            "SELECT commit_id,path FROM cr_commit_files WHERE path IS NOT NULL",
            1.2,
            &mut edges,
            &mut indices,
            &by_path,
        )?;
    }
    if edges.is_empty() {
        return Ok(());
    }
    let mut degree = vec![0.; paths.len()];
    for ((source, _), weight) in &edges {
        degree[*source] += weight;
    }
    let mut seed = vec![0.; paths.len()];
    for item in files.iter() {
        if item.score > 0.
            && let Some(i) = item
                .target
                .to_utf8()
                .and_then(|p| by_path.get(p.as_str()).copied())
        {
            seed[i] += item.score;
        }
    }
    let total = ken_retrieval::vector_math::sum_f64(&seed);
    if total <= 0. {
        return Ok(());
    }
    for value in &mut seed {
        *value /= total;
    }
    let anchors = seed
        .iter()
        .enumerate()
        .filter_map(|(i, s)| (*s > 0.).then_some(i))
        .collect::<BTreeSet<_>>();
    let mut mass = seed.clone();
    for _ in 0..3 {
        let mut walk = vec![0.; paths.len()];
        for ((source, target), weight) in &edges {
            walk[*target] += weight * mass[*source] / degree[*source];
        }
        for (i, value) in mass.iter_mut().enumerate() {
            *value = policy.ppr_alpha * seed[i] + (1. - policy.ppr_alpha) * walk[i];
        }
    }
    let mut neighbors = mass
        .into_iter()
        .enumerate()
        .filter(|(i, p)| !anchors.contains(i) && *p > 0.)
        .collect::<Vec<_>>();
    neighbors.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    let Some(max) = neighbors.first().map(|r| r.1) else {
        return Ok(());
    };
    let count = prefix(neighbors.len(), policy.ppr_max_neighbors);
    for (i, value) in neighbors.into_iter().take(count) {
        if value < policy.ppr_min_fraction * max {
            break;
        }
        let contribution = policy.ppr_max * (value / max);
        let path = &paths[i];
        if let Some(item) = files
            .iter_mut()
            .find(|it| it.target.to_utf8().as_deref() == Some(path))
        {
            item.score += contribution;
            item.reason = text::append(&item.reason, " + ", format!("ppr+{contribution:.1}"));
        } else {
            files.push(RankedItem::file(
                path.as_str(),
                contribution,
                format!("ppr({contribution:.1})"),
            ));
        }
    }
    Ok(())
}
