use super::{Result, StructuralError};
use rusqlite::{Connection, params};
use std::collections::BTreeMap;
pub(super) type Interval = (i64, i64, i64, i64);
pub(super) fn ready(db: &Connection, graph: i64) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM k2_graph_syntax_ready WHERE graph_id=?1)",
        [graph],
        |r| r.get(0),
    )?)
}
/// Compact parent-identity forest. Its preparation and traversal are cancellable;
/// persistence and transaction boundaries belong to the publication owner.
pub(super) struct Intervals {
    ids: Vec<i64>,
    first: Vec<Option<usize>>,
    sibling: Vec<Option<usize>>,
    stack: Vec<(Option<usize>, Option<i64>)>,
    counter: i64,
    last: i64,
    steps: usize,
    finished: bool,
}
impl Intervals {
    pub fn read(
        db: &Connection,
        graph: i64,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        let mut rows = Vec::<(i64, Option<i64>)>::new();
        let mut next = 0;
        loop {
            check()?;
            // Close the page cursor before a checkpoint may commit or renew.
            let page:Vec<(i64,i64,Option<i64>)>=db.prepare("SELECT ordinal,local_id,parent FROM k2_graph_operations WHERE graph_id=?1 AND ordinal>=?2 ORDER BY ordinal LIMIT 4096")?.query_map(params![graph,next],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?.collect::<rusqlite::Result<_>>()?;
            if page.is_empty() {
                break;
            }
            next = page.last().unwrap().0 + 1;
            rows.extend(page.into_iter().map(|(_, id, parent)| (id, parent)));
        }
        let mut positions = BTreeMap::new();
        for (i, (id, _)) in rows.iter().enumerate() {
            if i % 512 == 0 {
                check()?;
            }
            if positions.insert(*id, i).is_some() {
                return Err(StructuralError::Invalid("duplicate syntax identity"));
            }
        }
        let size = rows.len();
        let mut first = vec![None; size + 1];
        let mut sibling = vec![None; size];
        for i in (0..size).rev() {
            if i % 512 == 0 {
                check()?;
            }
            let parent = rows[i]
                .1
                .and_then(|id| positions.get(&id).copied())
                .unwrap_or(size);
            sibling[i] = first[parent];
            first[parent] = Some(i);
        }
        let stack = vec![(first[size], None)];
        let ids = rows.into_iter().map(|(id, _)| id).collect();
        Ok(Self {
            ids,
            first,
            sibling,
            stack,
            counter: 0,
            last: 0,
            steps: 0,
            finished: false,
        })
    }
    pub fn next_checked(
        &mut self,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Option<Interval>> {
        if self.finished {
            return Ok(None);
        }
        while let Some((node, start)) = self.stack.pop() {
            if self.steps.is_multiple_of(512) {
                check()?;
            }
            self.steps += 1;
            let Some(node) = node else { continue };
            if let Some(start) = start {
                return Ok(Some((self.ids[node], start, self.counter, self.last)));
            }
            let start = self.counter;
            self.counter += 1;
            self.last = self.ids[node];
            self.stack.extend([
                (self.sibling[node], None),
                (Some(node), Some(start)),
                (self.first[node], None),
            ]);
        }
        self.finished = true;
        if self.counter != self.ids.len() as i64 {
            return Err(StructuralError::Invalid("cyclic syntax parentage"));
        }
        Ok(None)
    }
}
/// A compatible already-READY legacy graph needs atomic syntax visibility.
/// The caller owns this transaction; every construction phase still checkpoints.
pub(super) fn ensure_atomic(
    db: &Connection,
    graph: i64,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    if ready(db, graph)? {
        return Ok(());
    }
    let mut intervals = Intervals::read(db, graph, check)?;
    db.execute("INSERT INTO k2_graph_syntax_ready VALUES(?1)", [graph])?;
    while let Some((id, start, end, last)) = intervals.next_checked(check)? {
        db.execute(
            "INSERT INTO k2_graph_syntax VALUES(?1,?2,?3,?4,?5)",
            params![graph, id, start, end, last],
        )?;
    }
    Ok(())
}
