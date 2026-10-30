use crate::{Clock, ContextNumerics, Policy, RankedItem, Result};
use rusqlite::{Connection, OptionalExtension, params};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug)]
pub struct SimilarPrompt {
    pub session_id: i64,
    pub sim: f64,
    pub days_ago: f64,
}
#[derive(Clone)]
pub(crate) struct Event {
    pub context: Option<i64>,
    pub path: String,
    pub event: String,
    pub weight: f64,
    pub iteration: i64,
}
fn weight(event: &str) -> f64 {
    match event {
        "retrieved" => 0.5,
        "read" => 1.,
        "edit" | "edited" | "write" => 2.,
        "cited" => 2.5,
        "dismissed" => -1.,
        _ => 0.,
    }
}
pub(crate) fn pattern_multiplier(pattern: &str) -> f64 {
    match pattern {
        "cited" | "edit_only" => 1.5,
        "read_edit" => 2.,
        "read_repeated" => 0.7,
        "read_skipped" | "dismissed" => 0.3,
        _ => 1.,
    }
}
fn classify(events: &[&str], edited_elsewhere: bool) -> &'static str {
    let has = |e: &str| events.contains(&e);
    let read = has("read") || has("retrieved");
    let edit = has("edit") || has("edited") || has("write");
    if has("cited") {
        "cited"
    } else if has("dismissed") {
        "dismissed"
    } else if read && edit {
        "read_edit"
    } else if edit {
        "edit_only"
    } else if events
        .iter()
        .filter(|e| matches!(**e, "read" | "retrieved"))
        .count()
        >= 3
    {
        "read_repeated"
    } else if read && edited_elsewhere {
        "read_skipped"
    } else {
        "neutral"
    }
}
pub(crate) fn events(conn: &Connection, session: i64, min: Option<i64>) -> Result<Vec<Event>> {
    let mut stmt=conn.prepare("SELECT context_id,target_path,event_type,weight,iteration FROM cr_interactions WHERE session_id=?1 AND target_kind='file' AND target_path IS NOT NULL AND (?2 IS NULL OR iteration>=?2)")?;
    Ok(stmt
        .query_map(params![session, min], |r| {
            Ok(Event {
                context: r.get(0)?,
                path: r.get(1)?,
                event: r.get(2)?,
                weight: r.get(3)?,
                iteration: r.get(4)?,
            })
        })?
        .collect::<rusqlite::Result<_>>()?)
}
pub(crate) fn historical_file_scores(events: &[Event]) -> Vec<(String, f64, String)> {
    aggregate(events, |_| 1., true)
}
fn aggregate(
    events: &[Event],
    decay: impl Fn(&Event) -> f64,
    historical: bool,
) -> Vec<(String, f64, String)> {
    let mut positions = BTreeMap::new();
    let mut groups = Vec::<(String, f64, Vec<&str>)>::new();
    let edited = events
        .iter()
        .filter(|e| {
            matches!(e.event.as_str(), "edit" | "edited") || (historical && e.event == "write")
        })
        .map(|e| &e.path)
        .collect::<BTreeSet<_>>();
    for event in events {
        let index = *positions.entry(&event.path).or_insert_with(|| {
            groups.push((event.path.clone(), 0., Vec::new()));
            groups.len() - 1
        });
        groups[index].1 += weight(&event.event) * event.weight * decay(event);
        groups[index].2.push(&event.event);
    }
    groups
        .into_iter()
        .filter_map(|(path, raw, events)| {
            let pattern = classify(&events, edited.iter().any(|p| **p != path));
            let raw = if pattern == "read_repeated" {
                raw.min(1.)
            } else {
                raw
            };
            (raw > 0.).then(|| (path, raw, pattern.to_owned()))
        })
        .collect()
}
pub fn reactive_scores(conn: &Connection, agent: &str, current: i64) -> Result<Vec<RankedItem>> {
    let session: Option<i64> = conn
        .query_row(
            "SELECT id FROM cr_sessions WHERE agent_id=?",
            [agent],
            |r| r.get(0),
        )
        .optional()?;
    let Some(session) = session else {
        return Ok(Vec::new());
    };
    let mut statement = conn.prepare(
        "SELECT id FROM cr_contexts WHERE session_id=? AND kind='user_prompt' ORDER BY id",
    )?;
    let ids = statement
        .query_map([session], |r| r.get::<_, i64>(0))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let ranks = ids
        .iter()
        .enumerate()
        .map(|(i, id)| (*id, i + 1))
        .collect::<BTreeMap<_, _>>();
    let events = events(conn, session, Some(current.saturating_sub(30).max(0)))?;
    Ok(aggregate(
        &events,
        |e| {
            let iteration = (-0.15 * (current.saturating_sub(e.iteration).max(0)) as f64).exp();
            let turn = e.context.and_then(|id| ranks.get(&id)).map_or(1., |rank| {
                0.5f64.powf(ids.len().saturating_sub(*rank).max(1).saturating_sub(1) as f64)
            });
            iteration * turn
        },
        false,
    )
    .into_iter()
    .map(|(path, raw, pattern)| {
        RankedItem::file(
            path,
            raw * pattern_multiplier(&pattern),
            format!("reactive:{pattern}"),
        )
    })
    .collect())
}
pub fn similar_past_sessions(
    conn: &Connection,
    q: &[f32],
    exclude: &str,
    clock: &Clock,
    numerics: &mut dyn ContextNumerics,
) -> Result<Vec<SimilarPrompt>> {
    let mut stmt=conn.prepare("SELECT session_id,embedding,created_at FROM cr_contexts WHERE kind='user_prompt' AND embedding IS NOT NULL AND session_id NOT IN(SELECT id FROM cr_sessions WHERE agent_id=?) ORDER BY created_at DESC,id DESC LIMIT 50")?;
    let rows = stmt
        .query_map([exclude], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Vec<u8>>(1)?,
                r.get::<_, i64>(2)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let scores = super::inline(
        numerics,
        q,
        &rows.iter().map(|r| r.1.clone()).collect::<Vec<_>>(),
    )?;
    Ok(scores
        .kept
        .into_iter()
        .zip(scores.scores)
        .filter_map(|(i, sim)| {
            let sim = f64::from(sim);
            if sim < 0.45 {
                return None;
            }
            Some(SimilarPrompt {
                session_id: rows[i].0,
                sim,
                days_ago: ((clock.now_ms as f64 - rows[i].2 as f64) / 86400000.).max(0.),
            })
        })
        .collect())
}
pub(crate) fn file_base_rates(conn: &Connection) -> Result<(i64, BTreeMap<String, i64>)> {
    let n = conn.query_row(
        "SELECT COUNT(DISTINCT session_id) FROM cr_session_scores",
        [],
        |r| r.get(0),
    )?;
    let mut stmt=conn.prepare("SELECT target_path,COUNT(DISTINCT session_id) FROM cr_session_scores WHERE score>0 AND target_path IS NOT NULL GROUP BY target_path")?;
    Ok((
        n,
        stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
            .collect::<rusqlite::Result<_>>()?,
    ))
}
pub(crate) fn base_rate_discount(n: i64, df: &BTreeMap<String, i64>, path: &str) -> f64 {
    if n < 5 {
        1.
    } else {
        1. / (1. + 4. * (df.get(path).copied().unwrap_or(0) as f64 + 1.) / (n as f64 + 2.))
    }
}
pub fn predictive_scores(
    conn: &Connection,
    similar: &[SimilarPrompt],
    policy: &Policy,
) -> Result<Vec<RankedItem>> {
    if similar.is_empty() {
        return Ok(Vec::new());
    }
    let ids = similar
        .iter()
        .map(|s| s.session_id)
        .collect::<BTreeSet<_>>();
    let mut evidence = BTreeMap::<i64, Vec<(String, f64, String)>>::new();
    let mut stmt=conn.prepare("SELECT target_path,score,pattern FROM cr_session_scores WHERE session_id=? AND target_kind='file' AND target_path IS NOT NULL")?;
    for id in ids {
        let rows = stmt
            .query_map([id], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, f64>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let mut retained = Vec::<(String, f64, String)>::new();
        for row in rows {
            if let Some(existing) = retained.iter_mut().find(|value| value.0 == row.0) {
                *existing = row;
            } else {
                retained.push(row);
            }
        }
        evidence.insert(id, retained);
    }
    let mut strongest = Vec::<((i64, String), f64)>::new();
    let mut positions = BTreeMap::new();
    for prompt in similar {
        let contribution = prompt.sim * prompt.sim * (-prompt.days_ago / 14.).exp();
        for (path, raw, pattern) in evidence.get(&prompt.session_id).into_iter().flatten() {
            let index = *positions
                .entry((prompt.session_id, path.clone()))
                .or_insert_with(|| {
                    strongest.push(((prompt.session_id, path.clone()), 0.));
                    strongest.len() - 1
                });
            strongest[index].1 = strongest[index]
                .1
                .max(contribution * raw * pattern_multiplier(pattern));
        }
    }
    let mut accum = Vec::<(String, f64)>::new();
    let mut positions = BTreeMap::new();
    for ((_, path), value) in strongest {
        let index = *positions.entry(path.clone()).or_insert_with(|| {
            accum.push((path, 0.));
            accum.len() - 1
        });
        accum[index].1 += value;
    }
    let (n, df) = if policy.lift {
        file_base_rates(conn)?
    } else {
        (0, BTreeMap::new())
    };
    Ok(accum
        .into_iter()
        .filter_map(|(path, mut value)| {
            let mut reason = "predictive".to_owned();
            if policy.lift {
                let discount = base_rate_discount(n, &df, &path);
                value *= discount;
                if discount < 0.99 {
                    reason = format!("predictive×lift{discount:.2}");
                }
            }
            let score = (value * 4.).min(6.);
            (score > 0.).then(|| RankedItem::file(path, score, reason))
        })
        .collect())
}
