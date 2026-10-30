use super::{
    kernel::{Kernel, Proof, State},
    model::{self, Atom, digest},
};
use crate::{Result, invalid, wire};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub fn ensure_schema(db: &Connection) -> Result<()> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS contexts(id TEXT PRIMARY KEY,revision INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS sources(context TEXT,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(context,id));CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,context TEXT,source TEXT,action TEXT,payload TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS checkpoints(context TEXT,world TEXT,rules_hash TEXT,state TEXT,PRIMARY KEY(context,world));")?;
    Ok(())
}
fn identifier<'a>(input: &'a Value, key: &str, default: Option<&'a str>) -> Result<&'a str> {
    let value = input
        .get(key)
        .map_or(default, Value::as_str)
        .ok_or_else(|| invalid("Expected a nonempty identifier of at most 256 characters"))?;
    model::name(value)?;
    Ok(value)
}
fn array(input: &Value, key: &str) -> Result<Vec<Value>> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(Vec::new()),
        Some(value) => value
            .as_array()
            .cloned()
            .ok_or_else(|| invalid("facts and rules must be arrays")),
    }
}
pub fn record(db: &Connection, input: &Value) -> Result<Value> {
    let source = identifier(input, "source", None)?;
    let context = identifier(input, "context", Some("main"))?;
    if source.starts_with('@') {
        return Err(invalid("Source IDs starting with @ are reserved"));
    }
    let evidence = input
        .get("evidence")
        .map_or(Some(""), Value::as_str)
        .ok_or_else(|| invalid("evidence must be text of at most 16000 characters"))?;
    if evidence.chars().count() > 16000 {
        return Err(invalid("evidence must be text of at most 16000 characters"));
    }
    let facts = array(input, "facts")?;
    let rules = array(input, "rules")?;
    if facts.len() + rules.len() > 500 {
        return Err(invalid("At most 500 facts/rules per source"));
    }
    let facts = facts
        .iter()
        .map(|v| Atom::read(v, true))
        .collect::<Result<Vec<_>>>()?;
    let rules = rules.iter().map(model::rule).collect::<Result<Vec<_>>>()?;
    let retract = input
        .get("retract")
        .map_or(Some(false), Value::as_bool)
        .ok_or_else(|| invalid("retract must be boolean"))?;
    if retract && (!facts.is_empty() || !rules.is_empty() || !evidence.is_empty()) {
        return Err(invalid("Retraction cannot also add content"));
    }
    if !retract && facts.is_empty() && rules.is_empty() {
        return Err(invalid(
            "Provide facts or rules; use ken_remember for unformalized notes",
        ));
    }
    let data = json!({"facts":facts,"rules":rules,"evidence":evidence});
    let payload = wire::json_ascii(&data);
    wire::transaction(db, || {
        db.execute("INSERT OR IGNORE INTO contexts VALUES(?,0)", [context])?;
        let old = db
            .query_row(
                "SELECT payload FROM sources WHERE context=? AND id=?",
                params![context, source],
                |r| r.get::<_, String>(0),
            )
            .optional()?;
        let revision =
            db.query_row("SELECT revision FROM contexts WHERE id=?", [context], |r| {
                r.get::<_, i64>(0)
            })?;
        if (old.as_deref() == Some(payload.as_str()) && !retract) || (old.is_none() && retract) {
            return Ok(json!({"changed":false,"revision":revision}));
        }
        if old.is_none() && !retract {
            let count = db.query_row(
                "SELECT COUNT(*) FROM sources WHERE context=?",
                [context],
                |r| r.get::<_, i64>(0),
            )?;
            if count >= 2000 {
                return Err(invalid("Prototype limit: 2000 sources per context"));
            }
        }
        db.execute(
            "DELETE FROM sources WHERE context=? AND id=?",
            params![context, source],
        )?;
        if !retract {
            db.execute(
                "INSERT INTO sources VALUES(?,?,?)",
                params![context, source, payload],
            )?;
        }
        db.execute(
            "DELETE FROM checkpoints WHERE context=? AND (world != ? OR ?)",
            params![context, "base", old.is_some()],
        )?;
        db.execute(
            "UPDATE contexts SET revision=revision+1 WHERE id=?",
            [context],
        )?;
        let action = if retract {
            "retract"
        } else if old.is_some() {
            "replace"
        } else {
            "insert"
        };
        if let Some(created) = input.get("created").and_then(Value::as_str) {
            db.execute(
                "INSERT INTO events(context,source,action,payload,created) VALUES(?,?,?,?,?)",
                params![context, source, action, payload, created],
            )?;
        } else {
            db.execute(
                "INSERT INTO events(context,source,action,payload) VALUES(?,?,?,?)",
                params![context, source, action, payload],
            )?;
        }
        Ok(
            json!({"changed":true,"revision":revision+1,"update":if old.is_some(){"invalidate_context"}else{"append_delta"}}),
        )
    })
}
pub fn ask(db: &Connection, input: &Value) -> Result<Value> {
    let query = Atom::read(&input["goal"], false)?;
    let context = identifier(input, "context", Some("main"))?;
    let budget = input
        .get("budget")
        .map_or(Some(1000), Value::as_u64)
        .filter(|b| *b <= 10000)
        .ok_or_else(|| invalid("budget must be 0..10000; seed must be integer"))?;
    let seed = input
        .get("seed")
        .map_or(Some(7), Value::as_i64)
        .ok_or_else(|| invalid("budget must be 0..10000; seed must be integer"))?;
    let assumptions = input.get("assumptions").cloned().unwrap_or(json!([]));
    let assumptions = if assumptions.is_null() {
        Vec::new()
    } else {
        assumptions
            .as_array()
            .filter(|a| a.len() <= 8)
            .cloned()
            .ok_or_else(|| invalid("At most eight ground assumptions"))?
    };
    let mut assumed = BTreeMap::new();
    for item in assumptions {
        let a = Atom::read(&item, true)?;
        assumed.insert(a.id(), a);
    }
    let assumed = assumed.into_values().collect::<Vec<_>>();
    let world = if assumed.is_empty() {
        "base".to_owned()
    } else {
        digest(&json!(assumed))
    };
    wire::transaction(db, || {
        let revision = db
            .query_row("SELECT revision FROM contexts WHERE id=?", [context], |r| {
                r.get::<_, i64>(0)
            })
            .optional()?
            .unwrap_or(0);
        let mut stmt = db.prepare("SELECT id,payload FROM sources WHERE context=? ORDER BY id")?;
        let rows = stmt
            .query_map([context], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        drop(stmt);
        let mut sources = BTreeMap::new();
        let mut atoms = Vec::new();
        let mut rules = Vec::new();
        for (sid, payload) in rows {
            let source: Value = serde_json::from_str(&payload)?;
            for a in source["facts"]
                .as_array()
                .ok_or_else(|| invalid("Invalid reasoning source facts"))?
            {
                atoms.push((Atom::read(a, true)?, sid.clone()));
            }
            for r in source["rules"]
                .as_array()
                .ok_or_else(|| invalid("Invalid reasoning source rules"))?
            {
                let clean = model::rule(r)?;
                rules.push(model::sourced(&clean, &sid, digest(&json!([sid, clean])))?);
            }
            sources.insert(sid, source);
        }
        if atoms.len() > 10000 || rules.len() > 2000 {
            return Err(invalid(
                "Prototype context limit: 10000 assertions and 2000 rules",
            ));
        }
        let mut all_atoms = atoms
            .iter()
            .map(|(a, _)| a.clone())
            .chain(assumed.iter().cloned())
            .collect::<Vec<_>>();
        for r in &rules {
            all_atoms.extend(r.body.iter().cloned());
            all_atoms.push(r.head.clone());
        }
        rules.extend(model::builtin_rules(&all_atoms));
        let rules_hash = digest(&json!(rules));
        let mut checkpoint = db
            .query_row(
                "SELECT rules_hash,state FROM checkpoints WHERE context=? AND world=?",
                params![context, world],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
            )
            .optional()?;
        if checkpoint.is_none() && world != "base" {
            checkpoint = db
                .query_row(
                    "SELECT rules_hash,state FROM checkpoints WHERE context=? AND world='base'",
                    [context],
                    |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
                )
                .optional()?;
        }
        let reused = checkpoint
            .as_ref()
            .is_some_and(|(hash, _)| hash == &rules_hash);
        let state = if reused {
            Some(serde_json::from_str::<State>(&checkpoint.unwrap().1)?)
        } else {
            None
        };
        let mut k = Kernel::new(rules, state, seed)?;
        let prior = k.fact_count();
        for (a, sid) in &atoms {
            k.add(
                a.clone(),
                Proof {
                    kind: "asserted".into(),
                    source: sid.clone(),
                    premises: Vec::new(),
                    rule: None,
                },
            );
        }
        for a in &assumed {
            k.add(
                a.clone(),
                Proof {
                    kind: "assumption".into(),
                    source: format!("@assumption:{}", a.id()),
                    premises: Vec::new(),
                    rule: None,
                },
            );
        }
        let metrics = k.run(&query, budget)?;
        let mut answer = k.answers(&query, 25);
        answer["context"] = json!(context);
        answer["revision"] = json!(revision);
        answer["world"] = json!(world);
        answer["query"] = query.data();
        answer["assumptions"] = json!(assumed);
        answer["metrics"] = metrics.clone();
        answer["reuse"] =
            json!({"checkpoint":reused,"prior_facts":prior,"new_work":metrics["work"]});
        answer["semantics"] = json!(
            "Conditional on supplied premises, interpretations and scope; not verified world truth."
        );
        let mut ids = BTreeSet::new();
        for a in answer["answers"].as_array().unwrap() {
            visit(&a["proof"], &mut ids);
            visit(&a["opposing_proof"], &mut ids);
        }
        for p in answer["opposition"].as_array().unwrap() {
            visit(p, &mut ids);
        }
        let mut evidence = serde_json::Map::new();
        for id in ids {
            if let Some(source) = sources.get(&id) {
                evidence.insert(id, source["evidence"].clone());
            }
        }
        answer["sources"] = Value::Object(evidence);
        answer["approximation"] = if answer["status"] == "unknown" {
            k.missing(&query)
        } else {
            json!([])
        };
        answer["answer"] = json!(answer_text(&answer));
        db.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)",
            params![context, world, rules_hash, serde_json::to_string(&k.state)?],
        )?;
        db.execute("DELETE FROM checkpoints WHERE context=? AND world!='base' AND rowid NOT IN (SELECT rowid FROM checkpoints WHERE context=? AND world!='base' ORDER BY rowid DESC LIMIT 16)",params![context,context])?;
        Ok(answer)
    })
}
fn visit(proof: &Value, ids: &mut BTreeSet<String>) {
    if !proof.is_object() {
        return;
    }
    if let Some(source) = proof["support"]["source"].as_str() {
        ids.insert(source.to_owned());
    }
    for p in proof["premises"].as_array().into_iter().flatten() {
        visit(p, ids);
    }
}
fn answer_text(answer: &Value) -> String {
    let message = match answer["status"].as_str().unwrap_or("unknown") {
        "supported" => "Hay apoyo en las premisas para la consulta.",
        "refuted" => "Las premisas apoyan la negación de la consulta.",
        "conflict" => "Hay apoyo tanto a favor como en contra.",
        _ => "No hay evidencia suficiente entre los hechos alcanzados.",
    };
    let mut text = if answer["assumptions"]
        .as_array()
        .is_some_and(|a| !a.is_empty())
    {
        format!("Bajo los supuestos indicados: {message}")
    } else {
        message.into()
    };
    if answer["metrics"]["complete"] != true {
        text.push_str(" La búsqueda está incompleta; podés continuar la misma consulta.");
    }
    text
}
