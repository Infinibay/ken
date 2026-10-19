use super::{Input, ProbeResult, schema};
use ken_store::{
    MaintenanceEvent, ProjectStore, StoreError, VectorSpace, allocate, compact, high_water,
    migrate_inline, reclaim_database, release, verify,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn bits(values: &[f32]) -> Vec<u8> {
    values.iter().flat_map(|n| n.to_le_bytes()).collect()
}
fn decode(raw: &str) -> ProbeResult<Vec<f32>> {
    if !raw.len().is_multiple_of(8) || !raw.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("F32 little-endian hex required".into());
    }
    let bytes = (0..raw.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&raw[i..i + 2], 16))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(bytes
        .chunks_exact(4)
        .map(|v| f32::from_le_bytes([v[0], v[1], v[2], v[3]]))
        .collect())
}
fn encoded(rows: &[Vec<f32>]) -> Vec<String> {
    rows.iter().map(|r| hex(&bits(r))).collect()
}
fn file(
    project: &ProjectStore,
    path: &str,
    embedding: Option<&[u8]>,
    slot: Option<i64>,
) -> ProbeResult<i64> {
    let conn = project.database().connection();
    conn.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) VALUES(?1,x'00',0,0,?2,?3)",rusqlite::params![path,embedding,slot])?;
    Ok(conn.last_insert_rowid())
}
fn metadata(project: &ProjectStore) -> ProbeResult<Value> {
    let conn = project.database().connection();
    let mut stmt = conn.prepare("SELECT key,value FROM meta ORDER BY key")?;
    let values = stmt
        .query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
        })?
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    Ok(serde_json::to_value(values)?)
}
fn segment_data(root: &Path) -> ProbeResult<BTreeMap<PathBuf, Vec<u8>>> {
    let mut result = BTreeMap::new();
    for entry in std::fs::read_dir(root.join(".ken/vectors"))? {
        let entry = entry?;
        if entry.path().extension().is_some_and(|e| e == "vec") {
            result.insert(entry.file_name().into(), std::fs::read(entry.path())?);
        }
    }
    Ok(result)
}
fn hashes(root: &Path) -> ProbeResult<Value> {
    let mut output = serde_json::Map::new();
    for (path, bytes) in segment_data(root)? {
        output.insert(
            path.to_str().ok_or("nonUTF8 generated segment")?.to_owned(),
            json!(hex(&Sha256::digest(bytes))),
        );
    }
    Ok(Value::Object(output))
}

pub fn observe(
    project: &mut ProjectStore,
    root: &Path,
    input: Input,
    correction: bool,
) -> ProbeResult<(Value, Value)> {
    let mut measurements = json!({});
    let output = match input {
        Input::Schema { legacy } => schema_history(project, legacy)?,
        Input::Metadata { values } => {
            let db = project.database();
            let mut observed = Vec::new();
            for value in values {
                db.set_meta("key", &value)?;
                observed.push(db.get_meta("key")?);
            }
            json!({"values":observed,"missing":db.get_meta("missing")?,"default":db.get_meta("missing")?.unwrap_or_else(||"fallback".into())})
        }
        Input::Marker { marker, model } => marker_history(project, &marker, &model)?,
        Input::Slots { rollback } => slot_history(project, rollback)?,
        Input::Cascade => cascade_history(project)?,
        Input::Unique => {
            file(project, "a.py", None, Some(7))?;
            let duplicate = file(project, "b.py", None, Some(7)).is_err();
            file(project, "c.py", None, None)?;
            file(project, "d.py", None, None)?;
            json!({"duplicate_rejected":duplicate,"null_slots":project.database().connection().query_row("SELECT count(*) FROM ci_files WHERE vec_slot IS NULL",[],|r|r.get::<_,i64>(0))?})
        }
        Input::Vectors {
            slots,
            vectors_le_hex,
            query_le_hex,
            dim,
        } => {
            let values = vectors_le_hex
                .iter()
                .map(|s| decode(s))
                .collect::<ProbeResult<Vec<_>>>()?;
            let query = decode(&query_le_hex)?;
            let store = project.vectors(VectorSpace::Files, dim, Some("fixture/model"))?;
            let result = if correction {
                let mut baseline = vec![0.; dim];
                if baseline.is_empty() {
                    return Err("positive dimension required".into());
                }
                baseline[0] = 1.;
                store.write(&[0], &[baseline], true)?;
                let before = segment_data(root)?;
                let rejected = matches!(
                    store.write(&slots, &values, false),
                    Err(StoreError::NonFinite)
                );
                json!({"rejected":rejected,"segments_unchanged":before==segment_data(root)?})
            } else {
                store.write(&slots, &values, false)?;
                let read = store.read(&slots)?;
                let count = usize::try_from(
                    slots
                        .iter()
                        .copied()
                        .max()
                        .ok_or("slots required")?
                        .checked_add(1)
                        .ok_or("slot count overflow")?,
                )?;
                let scores = store.scores(&query, count)?;
                store.flush()?;
                let persisted = project
                    .vectors(VectorSpace::Files, dim, None)?
                    .read(&slots)?;
                let segments: Vec<_> = segment_data(root)?
                    .into_iter()
                    .map(|(path, raw)| json!({"name":path,"bytes":raw.len()}))
                    .collect();
                json!({"read_le_hex":encoded(&read),"persisted_le_hex":encoded(&persisted),"scores_le_hex":hex(&bits(&scores)),"score_count":scores.len(),"manifest":store.manifest(),"segments":segments,"warnings":[]})
            };
            measurements = json!({"segment_sha256":hashes(root)?});
            result
        }
        Input::Migrate { twice } => migration_history(project, twice)?,
        Input::Compact { interrupt } => compact_history(project, root, interrupt)?,
        Input::Vacuum => {
            let mut unit = vec![0.; 128];
            unit[0] = 1.;
            let raw = bits(&unit);
            for i in 0..400 {
                file(project, &format!("{i}.py"), Some(&raw), None)?;
            }
            let moved = migrate_inline(project, 128, None, 2000, |_| {})?;
            let (before, after) = reclaim_database(project.database_mut())?;
            measurements = json!({"main_bytes_before":before,"main_bytes_after":after});
            json!({"moved":moved,"rows":project.database().connection().query_row("SELECT count(*) FROM ci_files WHERE vec_slot IS NOT NULL",[],|r|r.get::<_,i64>(0))?,"vacuum_completed":true})
        }
        Input::Manifest { field, value } => {
            if !["space", "dtype", "segment_rows", "model"].contains(&field.as_str()) {
                return Err("unknown fixture manifest field".into());
            }
            project.vectors(VectorSpace::Files, 4, Some("fixture/model"))?;
            let path = root.join(".ken/vectors/ci_files.json");
            let mut manifest: Value = serde_json::from_slice(&std::fs::read(&path)?)?;
            manifest[field] = value;
            let raw = serde_json::to_vec(&manifest)?;
            std::fs::write(&path, &raw)?;
            json!({"rejected":project.vectors(VectorSpace::Files,4,Some("fixture/model")).is_err(),"manifest_unchanged":std::fs::read(path)?==raw})
        }
        Input::SqlError => {
            project.database().connection().execute_batch("ALTER TABLE ci_passages DROP COLUMN implementation_start_line; PRAGMA query_only=ON;")?;
            let before = schema::snapshot(project.database().connection())?;
            let rejected = project.initialize().is_err();
            let after = schema::snapshot(project.database().connection())?;
            let present = schema::rows(
                project.database().connection(),
                "PRAGMA table_info(ci_passages)",
            )?
            .iter()
            .any(|r| r[1] == "implementation_start_line");
            json!({"migration_rejected":rejected,"column_present":present,"schema_unchanged":before==after})
        }
    };
    Ok((output, measurements))
}

fn schema_history(project: &mut ProjectStore, legacy: bool) -> ProbeResult<Value> {
    file(project, "é\0fixture.py", None, None)?;
    project.database().set_meta("keep", "value")?;
    let conn = project.database().connection();
    if legacy {
        for name in [
            "idx_ci_imports_resolution",
            "idx_ci_files_vec_slot",
            "idx_ci_symbols_vec_slot",
            "idx_ci_intent_sources_vec_slot",
        ] {
            conn.execute_batch(&format!("DROP INDEX {name}"))?;
        }
        for name in [
            "trg_ci_files_free_slot",
            "trg_ci_symbols_free_slot",
            "trg_ci_intent_free_slot",
        ] {
            conn.execute_batch(&format!("DROP TRIGGER {name}"))?;
        }
        for (table, column) in [
            ("ci_imports", "resolution"),
            ("ci_files", "vec_slot"),
            ("ci_symbols", "vec_slot"),
            ("ci_intent_sources", "vec_slot"),
            ("ci_passages", "implementation_start_line"),
        ] {
            conn.execute_batch(&format!("ALTER TABLE {table} DROP COLUMN {column}"))?;
        }
    }
    let before = schema::rows(
        conn,
        "SELECT id,path,content_hash FROM ci_files ORDER BY id",
    )?;
    project.initialize()?;
    let once = schema::snapshot(project.database().connection())?;
    project.initialize()?;
    let conn = project.database().connection();
    let mut settings = BTreeMap::new();
    for name in [
        "journal_mode",
        "synchronous",
        "foreign_keys",
        "busy_timeout",
    ] {
        settings.insert(
            name,
            schema::rows(conn, &format!("PRAGMA {name}"))?[0][0].clone(),
        );
    }
    Ok(
        json!({"schema":once,"idempotent":once==schema::snapshot(conn)?,"rows_preserved":before==schema::rows(conn,"SELECT id,path,content_hash FROM ci_files ORDER BY id")?,"metadata":metadata(project)?,"settings":settings}),
    )
}
fn marker_history(project: &mut ProjectStore, kind: &str, model: &str) -> ProbeResult<Value> {
    let conn = project.database().connection();
    conn.execute_batch("DROP TABLE meta; CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")?;
    project.database().set_meta("unrelated", "keep")?;
    project.database().set_meta("embed_doc_space", "9")?;
    match kind {
        "absent" => {}
        "null" | "empty" => {
            conn.execute(
                "INSERT INTO meta VALUES('embed_model',?1)",
                [if kind == "null" { None } else { Some("") }],
            )?;
        }
        "stored" => project.database().set_meta("embed_model", "stored/model")?,
        "vector-blob-empty" => {
            file(project, "a.py", Some(&[]), None)?;
        }
        "vector-slot-zero" => {
            file(project, "a.py", None, Some(0))?;
        }
        "vector-slot-negative" => {
            file(project, "a.py", None, Some(-1))?;
        }
        _ => return Err("unknown marker fixture".into()),
    }
    let before = metadata(project)?;
    // The caller's explicitly supplied model is the decision; storage owns freshness.
    let mut tx = project.database_mut().immediate()?;
    let present = tx.model_state()?.file_vectors_present;
    tx.pin_model_if_fresh(model, 2)?;
    tx.commit()?;
    Ok(
        json!({"metadata_before":before,"metadata_after":metadata(project)?,"selected":model,"file_vectors_present":present}),
    )
}
fn slot_history(project: &mut ProjectStore, rollback: bool) -> ProbeResult<Value> {
    let mut allocations = Vec::new();
    let mut tx = project.database_mut().immediate()?;
    if rollback {
        allocations.push(allocate(&mut tx, VectorSpace::Files, 4)?);
        drop(tx);
    } else {
        allocations.push(allocate(&mut tx, VectorSpace::Files, 3)?);
        release(&mut tx, VectorSpace::Files, &[1, 1])?;
        allocations.push(allocate(&mut tx, VectorSpace::Files, 2)?);
        allocate(&mut tx, VectorSpace::Symbols, 1)?;
        tx.commit()?;
    }
    let conn = project.database().connection();
    Ok(
        json!({"allocations":allocations,"high_water":high_water(conn,VectorSpace::Files)?,"free":schema::rows(conn,"SELECT space,slot FROM ci_vec_free ORDER BY space,slot")?,"other_high_water":high_water(conn,VectorSpace::Symbols)?,"in_transaction":!conn.is_autocommit()}),
    )
}
fn cascade_history(project: &ProjectStore) -> ProbeResult<Value> {
    let fid = file(project, "a.py", None, Some(3))?;
    let conn = project.database().connection();
    for (i, slot) in [10, 11].into_iter().enumerate() {
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(?1,'function',?2,1,2,?3)",rusqlite::params![fid,format!("f{i}"),slot])?;
    }
    conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at,vec_slot) VALUES(?1,'module_docstring','fixture',0,7)",[fid])?;
    conn.execute("DELETE FROM ci_files WHERE id=?1", [fid])?;
    let mut rows = BTreeMap::new();
    for space in VectorSpace::ALL {
        rows.insert(
            space,
            conn.query_row(&format!("SELECT count(*) FROM {space}"), [], |r| {
                r.get::<_, i64>(0)
            })?,
        );
    }
    Ok(
        json!({"free":schema::rows(conn,"SELECT space,slot FROM ci_vec_free ORDER BY space,slot")?,"rows":rows}),
    )
}
fn migration_history(project: &mut ProjectStore, twice: bool) -> ProbeResult<Value> {
    file(project, "matching.py", Some(&bits(&[3., 4., 0., 0.])), None)?;
    if !twice {
        file(project, "foreign.py", Some(&bits(&[1., 0.])), None)?;
    }
    let mut moved = vec![migrate_inline(project, 4, None, 1, |_| {})?];
    if twice {
        moved.push(migrate_inline(project, 4, None, 1, |_| {})?);
    }
    let conn = project.database().connection();
    let mut stmt = conn.prepare("SELECT id,path,embedding,vec_slot FROM ci_files ORDER BY id")?;
    let tuples = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<Vec<u8>>>(2)?,
                row.get::<_, Option<i64>>(3)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let rows:Vec<_>=tuples.iter().map(|(id,path,embedding,slot)|json!({"id":id,"path":path,"embedding_hex":embedding.as_ref().map(|v|hex(v)),"vec_slot":slot})).collect();
    let slots: Vec<_> = tuples.iter().filter_map(|r| r.3).collect();
    let store = project.vectors(VectorSpace::Files, 4, None)?;
    Ok(
        json!({"moved":moved,"rows":rows,"read_le_hex":encoded(&store.read(&slots)?),"verify":verify(conn,&store)?}),
    )
}
fn compact_history(project: &mut ProjectStore, root: &Path, interrupt: bool) -> ProbeResult<Value> {
    let files = (0..3)
        .map(|i| file(project, &format!("file{i}.py"), None, None))
        .collect::<ProbeResult<Vec<_>>>()?;
    let axes = [
        vec![1., 0., 0., 0.],
        vec![0., 1., 0., 0.],
        vec![0., 0., 1., 0.],
        vec![0., 0., 0., 1.],
    ];
    let matrix: Vec<_> = [3, 0, 3, 1, 3, 2].map(|i| axes[i].clone()).into();
    let mut original = BTreeMap::new();
    for space in VectorSpace::ALL {
        let mut tx = project.database_mut().immediate()?;
        allocate(&mut tx, space, 6)?;
        release(&mut tx, space, &[0, 2, 4])?;
        for (i, slot) in [1, 3, 5].into_iter().enumerate() {
            let conn = tx.connection();
            match space {
                VectorSpace::Files => {
                    conn.execute(
                        "UPDATE ci_files SET vec_slot=?1 WHERE id=?2",
                        rusqlite::params![slot, files[i]],
                    )?;
                }
                VectorSpace::Symbols => {
                    conn.execute("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(?1,'function',?2,1,2,?3)",rusqlite::params![files[0],format!("f{i}"),slot])?;
                }
                VectorSpace::IntentSources => {
                    conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at,vec_slot) VALUES(?1,'module_docstring',?2,0,?3)",rusqlite::params![files[0],format!("text{i}"),slot])?;
                }
            }
        }
        tx.commit()?;
        project.vectors(space, 4, Some("fixture/model"))?.write(
            &[0, 1, 2, 3, 4, 5],
            &matrix,
            true,
        )?;
        original.insert(
            space,
            schema::rows(
                project.database().connection(),
                &format!("SELECT id,vec_slot FROM {space} ORDER BY id"),
            )?,
        );
    }
    let mut events = Vec::new();
    let mut triggered = false;
    let result = if interrupt {
        // This isolated validation process models the original callback exception.
        // Product APIs have no failure switch or panic hook.
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let attempt = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            compact(project, 4, |event| {
                if let MaintenanceEvent::Compacted {
                    space,
                    before,
                    after,
                } = event
                {
                    events.push(format!("{space}: {before} -> {after} slots"));
                    triggered = true;
                    panic!("controlled validation callback interruption");
                }
            })
        }));
        std::panic::set_hook(previous);
        if attempt.is_ok() || !triggered {
            return Err("callback did not interrupt compaction".into());
        }
        None
    } else {
        Some(compact(project, 4, |event| {
            if let MaintenanceEvent::Compacted {
                space,
                before,
                after,
            } = event
            {
                events.push(format!("{space}: {before} -> {after} slots"));
            }
        })?)
    };
    let mut spaces = BTreeMap::new();
    let mut complete = true;
    let mut refs_preserved = true;
    for space in VectorSpace::ALL {
        let refs = schema::rows(
            project.database().connection(),
            &format!("SELECT id,vec_slot FROM {space} ORDER BY id"),
        )?;
        let slots = refs
            .iter()
            .map(|row| row[1].as_i64().ok_or("missing reference"))
            .collect::<Result<Vec<_>, _>>()?;
        let store = project.vectors(space, 4, None)?;
        let rows = store.read(&slots)?;
        complete &= rows == axes[..3];
        refs_preserved &= refs == original[&space];
        spaces.insert(space,json!({"references":refs,"read_le_hex":encoded(&rows),"verify":verify(project.database().connection(),&store)?}));
    }
    if interrupt {
        Ok(
            json!({"interrupted":triggered,"complete_mapping":complete,"original_references":refs_preserved,"journal_absent":!root.join(".ken/vectors-maintenance.json").exists()}),
        )
    } else {
        Ok(
            json!({"result":result,"events":events,"interrupted":false,"complete_mapping":complete,"spaces":spaces}),
        )
    }
}
