//! Iterative import-graph algorithms over dense node indices ordered by file ID.
use std::collections::{BTreeMap, BTreeSet, VecDeque};
pub(super) type Graph = Vec<Vec<usize>>;

pub(super) fn reverse(graph: &Graph) -> Graph {
    let mut result = vec![Vec::new(); graph.len()];
    for (src, destinations) in graph.iter().enumerate() {
        for &dst in destinations {
            result[dst].push(src);
        }
    }
    result
}
pub(super) fn undirected(graph: &Graph) -> Graph {
    let mut result = vec![BTreeSet::new(); graph.len()];
    for (src, destinations) in graph.iter().enumerate() {
        for &dst in destinations {
            result[src].insert(dst);
            result[dst].insert(src);
        }
    }
    result
        .into_iter()
        .map(|s| s.into_iter().collect())
        .collect()
}
pub(super) fn strongly_connected(graph: &Graph) -> Vec<Vec<usize>> {
    let mut index = vec![usize::MAX; graph.len()];
    let mut low = index.clone();
    let mut on_stack = vec![false; graph.len()];
    let mut stack = Vec::new();
    let mut components = Vec::new();
    let mut counter = 0;
    for start in 0..graph.len() {
        if index[start] != usize::MAX {
            continue;
        }
        let mut work = vec![(start, 0)];
        index[start] = counter;
        low[start] = counter;
        counter += 1;
        stack.push(start);
        on_stack[start] = true;
        while let Some(&(v, next)) = work.last() {
            if let Some(&w) = graph[v].get(next) {
                work.last_mut().unwrap().1 += 1;
                if index[w] == usize::MAX {
                    index[w] = counter;
                    low[w] = counter;
                    counter += 1;
                    stack.push(w);
                    on_stack[w] = true;
                    work.push((w, 0));
                } else if on_stack[w] {
                    low[v] = low[v].min(index[w]);
                }
                continue;
            }
            work.pop();
            if let Some(&(parent, _)) = work.last() {
                low[parent] = low[parent].min(low[v]);
            }
            if low[v] == index[v] {
                let mut component = Vec::new();
                loop {
                    let w = stack.pop().unwrap();
                    on_stack[w] = false;
                    component.push(w);
                    if w == v {
                        break;
                    }
                }
                components.push(component);
            }
        }
    }
    components
}
pub(super) fn condensation_layers(graph: &Graph, components: &[Vec<usize>]) -> Vec<usize> {
    let mut owner = vec![0; graph.len()];
    for (i, component) in components.iter().enumerate() {
        for &v in component {
            owner[v] = i;
        }
    }
    let mut edges = vec![BTreeSet::new(); components.len()];
    for (a, destinations) in graph.iter().enumerate() {
        for &b in destinations {
            if owner[a] != owner[b] {
                edges[owner[a]].insert(owner[b]);
            }
        }
    }
    let mut indegree = vec![0; components.len()];
    for destinations in &edges {
        for &dst in destinations {
            indegree[dst] += 1;
        }
    }
    let mut queue = indegree
        .iter()
        .enumerate()
        .filter_map(|(i, n)| (*n == 0).then_some(i))
        .collect::<VecDeque<_>>();
    let mut layers = vec![0; components.len()];
    while let Some(v) = queue.pop_front() {
        for &w in &edges[v] {
            layers[w] = layers[w].max(layers[v] + 1);
            indegree[w] -= 1;
            if indegree[w] == 0 {
                queue.push_back(w);
            }
        }
    }
    layers
}
pub(super) fn communities(undirected: &Graph) -> Vec<Vec<usize>> {
    let mut label = (0..undirected.len()).collect::<Vec<_>>();
    for _ in 0..20 {
        let mut changed = false;
        for (v, neighbors) in undirected.iter().enumerate() {
            if neighbors.is_empty() {
                continue;
            }
            let mut counts = BTreeMap::<usize, usize>::new();
            for &w in neighbors {
                *counts.entry(label[w]).or_default() += 1;
            }
            let (&best, _) = counts
                .iter()
                .min_by_key(|(label, n)| (std::cmp::Reverse(**n), **label))
                .unwrap();
            if label[v] != best {
                label[v] = best;
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    // Preserve first-node insertion order of Python's groups dictionary, also
    // used by the modularity sum and stable cluster tie ordering.
    let mut group_index = BTreeMap::new();
    let mut groups = Vec::<Vec<usize>>::new();
    for (v, label) in label.into_iter().enumerate() {
        let i = *group_index.entry(label).or_insert_with(|| {
            groups.push(Vec::new());
            groups.len() - 1
        });
        groups[i].push(v);
    }
    groups
}
pub(super) fn pagerank(graph: &Graph) -> (Vec<f64>, bool) {
    let n = graph.len() as f64;
    if n == 0.0 {
        return (Vec::new(), true);
    }
    let mut rank = vec![1.0 / n; graph.len()];
    for _ in 0..40 {
        let dangling = graph
            .iter()
            .enumerate()
            .filter(|(_, e)| e.is_empty())
            .map(|(v, _)| rank[v])
            .sum::<f64>();
        let mut next = vec![(1.0 - 0.85) / n + 0.85 * dangling / n; graph.len()];
        for (v, destinations) in graph.iter().enumerate() {
            if destinations.is_empty() {
                continue;
            }
            let share = 0.85 * rank[v] / destinations.len() as f64;
            for &w in destinations {
                next[w] += share;
            }
        }
        let delta = next
            .iter()
            .zip(&rank)
            .map(|(a, b)| (a - b).abs())
            .sum::<f64>();
        rank = next;
        if delta < 1e-9 {
            return (rank, true);
        }
    }
    (rank, false)
}
pub(super) fn modularity(groups: &[Vec<usize>], undirected: &Graph) -> f64 {
    let m = undirected.iter().map(Vec::len).sum::<usize>() as f64 / 2.0;
    if m <= 0.0 {
        return 0.0;
    }
    let mut result = 0.0;
    for group in groups {
        let members = group.iter().copied().collect::<BTreeSet<_>>();
        let internal = group
            .iter()
            .flat_map(|&v| &undirected[v])
            .filter(|w| members.contains(*w))
            .count() as f64
            / 2.0;
        let degree = group.iter().map(|&v| undirected[v].len()).sum::<usize>() as f64;
        let fraction = degree / (2.0 * m);
        result += internal / m - fraction * fraction;
    }
    result
}
