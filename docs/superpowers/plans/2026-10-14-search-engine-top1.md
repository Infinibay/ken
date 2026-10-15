# Engine de búsqueda top‑1 ≥90% — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans para ejecutar este plan tarea por tarea. Una ejecución con subagentes requiere selección explícita del usuario; no está seleccionada. Los pasos usan checkboxes para seguimiento.

**Goal:** Encontrar primero el archivo y la función o fragmento correctos, con evidencia visible, en al menos 90% de consultas nuevas de aceptación.

**Architecture:** Un núcleo compartido recupera entidades y pasajes por identidad, léxico y semántica; un ordenador compara evidencia y un presentador muestra fuente vigente. El indexador y sus garantías incrementales siguen siendo los dueños del estado. CLI, MCP, ranker de contexto y responsabilidad consumen ese núcleo mediante adaptadores.

**Tech Stack:** Python 3.12, SQLite/FTS5, NumPy, parsers y vectores existentes; pytest/mypy. Modelos locales adicionales sólo como experimentos versionados que justifiquen su promoción.

**Spec:** [Diseño y protocolo](../specs/2026-10-14-search-engine-top1-design.md). Estado del plan: aprobado por el usuario el 2026-10-14; ejecución nativa iniciada.

## Global Constraints

- `strict_top1 >= 0.90` global, macro por repositorio y en comportamiento/EN/ES; archivo y función o fragmento correctos con evidencia visible.
- 300 positivos en 12 repositorios nuevos (25 por repositorio), 180 EN/120 ES; 210 comportamiento, 45 identidad y 45 usos/tests/docs. Al menos 60 negativos separados.
- Identificadores únicos calificados: 100% en regresión determinista. `candidate_recall@100 >= 0.98` es checkpoint de desarrollo.
- Aceptación: 10 resultados, máximo total 12000 caracteres y hasta 40 líneas visibles por resultado; errores y abstenciones positivas cuentan cero.
- Sin llamadas remotas para procesar código/consultas; sin rebajar el gate, adulterar etiquetas, hardcodear repositorios o introducir supresiones/stubs.
- Preservar modificaciones anteriores del usuario y contratos públicos mediante adaptadores/versionado. El `score` legado sigue significando coseno.
- Promover el mismo perfil predeterminado que supera el gate; no certificar una configuración costosa oculta mientras se distribuye otra.
- Aceptación usa `purpose="auto"`; las etiquetas del caso, incluido propósito/idioma/answerable y referencia, no se pasan como pistas al motor.

## Review Focus

1. Implementaciones homónimas, closures, overloads y reexports: no confundir un uso con su propietario; pruebas en tareas 3–4.
2. Edición/borrado durante consulta o reindexación fallida: no citar contenido de otra generación; tareas 4 y 9.
3. Preguntas ES/EN con negación, errores entre comillas y símbolos de puntuación: no perder el sentido ni producir sintaxis FTS; tareas 3 y 5.
4. Funciones largas, evidencia al final y muchos métodos por archivo: recuperar y mostrar el pasaje correcto sin premio por duplicación; tareas 4, 6 y 9.
5. Consumidores de formato y proyectos sin nueva migración/modelo: conservar contratos o devolver estado accionable, sin resultados silenciosamente vacíos; tareas 4 y 10.

## Preparación y mapa de responsabilidades

Antes de código: registrar `git status`, HEAD, diff binario y hashes de los archivos nuevos anteriores; crear una copia de trabajo aislada que incluya ese estado como baseline. Usar herramientas nativas de worktree; no partir del HEAD limpio si omite cambios investigados. No ejecutar `git add .`. Los commits de las tareas incluyen sólo archivos/hunks propios; si no es posible separarlos, conservar diff propio sin commit y explicar el solapamiento.

Los nuevos módulos son límites de responsabilidad, no una clase por señal:

| Archivos | Responsabilidad |
|---|---|
| `src/ken/retrieval/model.py` | Tipos compartidos, identidad, procedencia y rangos. |
| `src/ken/retrieval/passages.py`, `storage.py` | Extraer evidencia y mantener su generación dentro del ciclo del indexador. |
| `src/ken/retrieval/lexical.py`, `candidates.py` | Recuperación léxica y unión con lookup/vistas densas. |
| `src/ken/retrieval/ranking.py`, `service.py` | Ordenar entidades y coordinar una búsqueda. |
| `src/ken/retrieval/presentation.py` | Fuente visible, presupuesto, frescura y formato. |
| `src/ken/bench/retrieval.py`, `dataset.py` | Extender `ken bench` con evaluación estricta sin cambiar la métrica histórica. |
| `experiments/search-engine/` | Protocolos, entrenamiento, ablaciones y reportes; sin etiquetas de aceptación accesibles al optimizador. |

Tipos compartidos, definidos en tarea 4: `Span(start_line, end_line)` inclusivo; `EntityKey(path, kind, qualname, owner, definition_ordinal)` independiente del rowid y único dentro de una instantánea; `Passage(entity, span, fields, source_hash)`; `SearchRequest(query, target, purpose, limit, max_chars, explain)`; `Candidate(entity, passages, signals)`; `CodeMatch(entity, score, evidence, source_hash)`; `SearchResponse(results, profile_version, truncated, omitted_count, warnings)`. `definition_ordinal` distingue overloads/definiciones con igual nombre, tipo y propietario en orden de fuente; no promete identidad inmutable entre ediciones. `target` es `file|symbol|passage`; `purpose` es `auto|implementation|usage|tests|documentation`. El presentador añade estado por fragmento y rangos visibles; no concatena regiones discontinuas fingiendo un solo rango. El corpus normaliza rutas relativas al proyecto.

Para todos los cambios de código: primero prueba roja de comportamiento público, luego implementación mínima, prueba verde y revisión del diff. `ken_recall` antes de editar; para cambios compartidos, revisar `blast_radius`, `cochange` y tests con Ken. No reescribir los archivos completos que contienen cambios previos.

## Task 1 — Un evaluador que pueda rechazar un 89%

**Files:** crear `src/ken/bench/__init__.py`, `src/ken/bench/dataset.py`, `src/ken/bench/retrieval.py`, `tests/bench/test_retrieval.py`; modificar `src/ken/cli.py` sólo en el cableado de `bench`.

**Interfaces:** consume resultados de búsqueda como records JSON versionados; produce `load_dataset(path: Path) -> RetrievalDataset`, `evaluate(cases, responses) -> RetrievalReport` y `check_gate(report, policy) -> list[str]`. El gate usa fracciones sin redondear y los denominadores del dataset, no sólo respuestas recibidas.

Un caso v2 contiene `id`, `repo_id`, `repo_commit`, `query`, `language`, `purpose`, `behavior_group`, `answerable` y `alternatives`. Cada alternativa contiene `path`, `source_hash`, `entity` opcional y `anchors: list[Span]`; una alternativa se satisface completa, sin mezclar anclas de alternativas distintas. La identidad usa la forma de `EntityKey` del mapa. `RetrievalReport` contiene numeradores/denominadores por estrato, respuestas inválidas y procedencia. Los records normalizados incluyen entidad, fragmentos visibles/hash y estado; los adaptadores del evaluador pueden hidratar una respuesta legada usando lectura de fuente y el mismo presupuesto, registrando ese trabajo adicional. Así el baseline de recuperación no queda en cero artificialmente por no tener todavía el formato v2.

- [ ] RED: `test_gate_rejects_269_of_300_and_accepts_270` afirma rechazo/aceptación; `test_file_only_or_wrong_owner_is_a_miss`; `test_docstring_only_does_not_satisfy_behavior_anchor`; `test_errors_and_abstentions_remain_in_denominator`; `test_global_90_cannot_hide_spanish_failure`; `test_gold_metadata_never_enters_search_request`; `test_legacy_bench_retains_its_metrics`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/bench/test_retrieval.py -q`; debe fallar por evaluador ausente o aserciones, no por fixtures rotos.
- [ ] Implementar esquema v2 con alternativas completas de referencia, anclas y hashes, manifiesto de perfil y estratos; `ken bench --engine retrieval --gate POLICY DATASET --json`. Mantener los argumentos/datasets actuales sin `--engine`.
- [ ] GREEN: ejecutar el comando anterior y `.venv/bin/python -m pytest tests/test_cli_bench.py -q`. Ambos pasan; incluir casos 0 resultados, rangos fuera de fuente y registros faltantes/duplicados.
- [ ] Commit propio: `test: add strict retrieval top1 acceptance gate`.

## Task 2 — Datos de desarrollo y reserva sin contaminación

**Files:** crear `experiments/search-engine/protocol.md`, `experiments/search-engine/datasets/development.jsonl`, `experiments/search-engine/datasets/manifest.json`, `experiments/search-engine/curate.py`, `tests/bench/test_dataset_partition.py`. La reserva vive en ubicación separada del contexto del implementador.

**Interfaces:** consume `load_dataset`; produce datasets de ≥400 positivos de desarrollo, la reserva de la spec y un manifiesto con `repo_commit`, hashes, grupos de paráfrasis/implementación, rol, idioma, objetivo y revisión de referencias.

- [ ] RED: `test_partitions_reject_shared_repositories_or_behavior_groups`; `test_acceptance_mix_is_exact_and_labels_match_source`; `test_used_holdout_cannot_be_reused_as_blind`. Una duplicación deliberada debe invalidar el manifiesto.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/bench/test_dataset_partition.py -q`; comprobar fallos previstos.
- [ ] Curar preguntas desde comportamientos reales, con errores/configuración/usos/tests; validar código y alternativas antes de correr motores. Congelar los 60 casos antiguos como regresión. La reserva requiere un curador/revisor independiente del ajuste; si no está disponible, entregar desarrollo y declarar aceptación pendiente, sin simular cegamiento.
- [ ] GREEN: mismo pytest y `ken bench --engine retrieval --gate ...` en fixtures sintéticos. Registrar baseline real en desarrollo, también con presupuesto visible. No ejecutar todavía la reserva real.
- [ ] Commit propio: `test: freeze retrieval datasets and evaluation protocol` (sin secretos ni reserva expuesta al ajuste).

**Checkpoint A:** definición y medición auditables. Revisar métricas antiguas frente a las nuevas y cobertura de etiquetas. No optimizar un objetivo mal puntuado.

## Task 3 — Frontera de consulta y nombres exactos independientes

**Files:** modificar `src/ken/grep.py`, `src/ken/search.py`, `src/ken/nametokens.py`; crear `tests/test_search_query_contract.py`; extender `tests/test_search_cli.py`.

**Interfaces:** conservar `search_files(...)`/`search_symbols(...)`; añadir lookup exacto interno sobre índice SQL antes de fusión, independiente de `_scored_from_store`. `literal=True` conserva semántica literal.

- [ ] RED: `test_question_mark_and_quotes_are_safe_fts_input` con `?`, comillas, paréntesis, `C++`, `foo.bar`, `->`, `OR` como texto; `test_unique_exact_symbol_outside_dense_top512_is_first`; `test_ambiguous_short_name_keeps_multiple_owners`; `test_query_preserves_negation_and_identifiers` en EN/ES.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/test_search_query_contract.py tests/test_search_cli.py -q`; verificar la reproducción roja del defecto conocido.
- [ ] Parametrizar SQL y construir términos FTS escapados mediante tokenización compartida; no enviar prosa como gramática FTS. Mantener identificadores completos y componentes. Lookup por nombre/qualname sin requerir embedding presente; exacto único calificado tiene precedencia, nombre ambiguo no inventa certeza.
- [ ] GREEN: mismo comando más `.venv/bin/python -m pytest tests/test_nametokens.py -q`; correr regresión de los diez identificadores conocidos y registrar resultados, sin atribuirle al nuevo engine trabajo aún no hecho.
- [ ] Commit propio: `fix: preserve prose queries and retrieve exact identities independently`.

## Task 4 — Pasajes con propietario, fuente y generación

**Files (4a):** crear `src/ken/retrieval/__init__.py`, `model.py`, `passages.py`, `tests/retrieval/test_passages.py`. Extender los parsers en slices posteriores de esta misma tarea: primero `src/ken/parsers/types.py`, `python.py` y `tests/parsers/test_python.py`; luego `javascript.py`/`typescript.py`, `go.py`, `rust.py` y `java.py` con sus tests existentes, un lenguaje por slice.

**Interfaces:** produce los tipos del mapa y `extract_passages(source: bytes, parsed, policy) -> list[Passage]`. Los campos incluyen identidad, firma, doc completo, cuerpo, literales, ruta y papel; `source_hash` corresponde a los bytes originales.

- [ ] RED: `test_long_function_preserves_late_behavior_anchor`; `test_nested_and_homonymous_owners_are_distinct`; `test_decorators_overloads_unicode_and_crlf_keep_source_coordinates`; `test_module_fragment_has_no_fabricated_symbol`; fallback explícito sin gramática. Cada pasaje debe mapear a bytes/líneas reales y al propietario más estrecho demostrado.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_passages.py -q`; observar fallos de extracción ausente.
- [ ] Implementar límites por sentencias y políticas 128/256/384 tokens. Reutilizar hechos de parser/índice estructural existentes; no crear un parser Python paralelo ni cambiar el significado de columnas antiguas. Los campos de firma/doc completo/propietario se añaden de forma optativa al contrato compartido; conservar `docstring` legado y migrar identidades nuevas mediante el indexador. Añadir fixtures por lenguaje del gate mediante sus adaptadores, conservando el mismo contrato.
- [ ] GREEN: mismo comando y suites de parsers afectados; registrar cobertura/fallbacks por lenguaje. Commit propio: `feat: extract owned source passages for retrieval`.

**Files (4b):** crear `src/ken/retrieval/storage.py`, `tests/retrieval/test_storage.py`; modificar `src/ken/schema.sql`, `src/ken/db.py`, `src/ken/indexer.py` en pasos de persistencia/migración.

**Interfaces:** `replace_file_passages(conn, file_id, passages, generation) -> None`, `load_passages(conn, entity) -> list[Passage]`; la sustitución participa en la transacción del indexador. Integrar slots vectoriales nuevos con el almacén existente, sin tabla paralela de símbolos.

- [ ] RED: `test_edit_delete_and_parser_change_invalidate_passages`; `test_failure_does_not_publish_partial_generation`; `test_model_change_cannot_reuse_incompatible_vectors`; `test_legacy_database_migrates_without_losing_findings`; simular borrado y reindexación con lectores concurrentes.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_storage.py -q`; verificar rojo antes de migrar.
- [ ] Implementar esquema/versiones y ciclo de reemplazo/borrado de pasajes. Las tareas 4c y 5 integran vectores/postings a esta misma publicación; no declararlos consistentes antes de esa integración. Si cambia formato/modelo, estado explícito de reindexación; no mezclar generaciones.
- [ ] GREEN: mismo comando más `.venv/bin/python -m pytest tests/test_indexer.py tests/test_db.py tests/test_index_queue.py tests/test_watcher.py -q`. Commit propio: `feat: persist retrieval passages with atomic index generations`.

**Files (4c):** modificar `src/ken/vectors.py`, `src/ken/retrieval/storage.py`, `src/ken/db.py`; crear `tests/retrieval/test_vector_snapshot.py`; extender `tests/test_vectors.py`.

**Interfaces:** `retrieval_snapshot(conn, root)` devuelve un context manager con generación, filas y slots activos consistentes; el escritor publica slots nuevos y retira generaciones para compactación posterior. La política sólo cambia los nuevos espacios de identidad/comportamiento; los consumidores legados no reciben una garantía que aún no implementan.

- [ ] RED: `test_slot_reuse_cannot_pair_old_score_with_new_owner` fuerza la carrera con barreras entre barrido y resolución; `test_compaction_keeps_active_reader_generation_alive`; `test_rollback_never_publishes_unwritten_vectors`; `test_retired_generation_is_reclaimed_after_last_reader`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_vector_snapshot.py -q`; reproducir la carrera, sin depender de sleeps probabilísticos.
- [ ] Añadir espacios y manifiestos de vistas al almacén existente. El lector puntúa sólo slots activos de su instantánea SQL; el escritor no recicla slots retirados que esa generación pueda estar leyendo. Publicar flush antes de commit y compactar mediante rotación de generación con lectores registrados. No introducir un segundo vector store; medir crecimiento de disco y coste de snapshots.
- [ ] GREEN: mismo comando y `.venv/bin/python -m pytest tests/test_vectors.py tests/test_vectors_daemon.py -q`. Commit propio: `fix: keep retrieval vector snapshots coherent during reindexing`.

## Task 5 — Índice léxico incremental por campos

**Files:** crear `src/ken/retrieval/lexical.py`, `tests/retrieval/test_lexical.py`; modificar `storage.py`, `src/ken/grep.py` y `schema.sql` para postings/estadísticas y su actualización.

**Interfaces:** `lexical_candidates(conn, request: SearchRequest, limit: int) -> list[Candidate]`; usa pasajes de `storage` y la tokenización compartida. `replace_file_passages` actualiza frecuencias/longitudes de la misma generación.

- [ ] RED: `test_rare_error_literal_retrieves_implementation`; `test_bm25f_matches_hand_calculation`; `test_delete_updates_document_frequency`; `test_empty_fields_are_finite`; `test_query_does_not_read_every_source_file`; EN/ES y negación permanecen en señales.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_lexical.py -q`; comprobar fallos previstos.
- [ ] Implementar BM25 de control y BM25F de la spec; no sumar scores crudos de otro canal. Llevar sincronización del texto al indexador manteniendo la vigencia documentada de `scope=text`; el lookup literal continúa leyendo su superficie autorizada.
- [ ] GREEN: mismo comando y pruebas de búsqueda de tarea 3. Reportar recall por canal y tamaño/coste de postings. Commit propio: `feat: add incremental fielded lexical retrieval`.

**Checkpoint B:** cobertura antes de sofisticar ranking. Inspeccionar pérdidas por extracción, propietario y ausencia léxica. Reparar esas pérdidas primero; no compensarlas con nombres de repositorios o boosts de archivos de referencia.

## Task 6 — Vistas densas y unión de candidatos

**Files:** crear `src/ken/retrieval/candidates.py`, `service.py`, `tests/retrieval/test_candidates.py`; modificar `src/ken/embedder/__init__.py` y `storage.py` mediante integración separada si excede un slice de cinco archivos.

**Interfaces:** `retrieve(conn, root, request: SearchRequest, profile) -> list[Candidate]` consume `retrieval_snapshot`; identidad y comportamiento tienen matrices/versiones propias. `search(conn, root, request: SearchRequest, *, profile=None) -> SearchResponse` coordina recuperación, ranking y presentación; inicialmente usa RRF de control y evidencia mínima fiel sin interfaces vacías para módulos futuros.

- [ ] RED: `test_union_recovers_answer_absent_from_each_other_channel`; `test_exact_lookup_survives_preselection`; `test_duplicate_passages_do_not_consume_entity_budget`; `test_file_search_exposes_matching_member_not_first_eight`; errores de modelo/corpus se informan, no producen lista vacía silenciosa.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_candidates.py -q`; verificar rojo.
- [ ] Implementar unión hasta 100 por canal, agrupación por entidad, preselección 100 con RRF de baseline y reserva de exactos. Registrar candidatos previos/posteriores, scores originales y razones de descarte. Separar vistas de identidad de las del cuerpo; no reemplazar el embedding antiguo por una función larga.
- [ ] GREEN: mismo comando y evaluación de desarrollo por canal. Si `candidate_recall@100 < 0.98`, clasificar pérdidas y repetir tareas 4–6 con protocolo registrado antes de pasar a la segunda etapa.
- [ ] Commit propio: `feat: unify identity lexical and passage candidate retrieval`.

## Task 7 — Elegir representación/modelo con controles

**Files:** crear `experiments/search-engine/compare_representations.py`, `model_protocol.json`, `tests/retrieval/test_model_profiles.py`; modificar `src/ken/retrieval/service.py` y `src/ken/embedder/__init__.py` sólo para perfiles/versiones necesarios.

**Interfaces:** consume `search(..., profile=...)`; produce `profile.json` con revisión exacta de modelo, extractor, tokenizer, presupuesto, backend y normalización. Ningún perfil referencia gold ni nombres de repositorios.

- [ ] RED: `test_profile_requires_immutable_model_revision`; `test_wrong_dimension_or_prefix_is_rejected`; `test_missing_optional_backend_is_actionable`; `test_identity_and_behavior_profiles_cannot_share_incompatible_cache`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_model_profiles.py -q`; verificar rojo.
- [ ] Evaluar matriz controlada de modelo actual/Potion/E5 multilingüe y presupuestos 128/256/384, con misma recuperación léxica. Revisar documentación oficial de prefijos/truncamiento y licencias antes de descargar revisiones. Congelar selección mediante validación por repositorio y calidad EN/ES; publicar p50/p95, indexación, RAM/disco. Cambiar una dimensión por comparación causal.
- [ ] GREEN: mismo pytest; guardar resultados crudos y selección reproducible. Un cambio de modelo que sólo mejora archivo @5 no cumple el criterio. Commit propio: `perf: select retrieval representations by repository-held-out quality`.

## Task 8 — Ordenar evidencia y justificar cada señal

**Files:** crear `src/ken/retrieval/ranking.py`, `tests/retrieval/test_ranking.py`, `experiments/search-engine/train_ranker.py`, `signal_audit.csv`; modificar `service.py`.

**Interfaces:** `rank_candidates(request, candidates, ranker) -> list[CodeMatch]`; `fit_ranker(training_groups, validation_groups, seed) -> RankerArtifact`. El artefacto fija esquema de features, normalización, pesos y hashes de entrenamiento; la traza permite reconstruir el score.

- [ ] RED: `test_duplicate_evidence_cannot_outvote_single_correct_owner`; `test_test_purpose_does_not_penalize_tests`; `test_recent_touch_does_not_override_unique_identity`; `test_score_trace_reconstructs_rank`; `test_validation_repo_cannot_fit_scaler_or_weights`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_ranking.py -q`; comprobar fallos previstos.
- [ ] Implementar RRF de control y ranker lineal por pares con NumPy, L2 y pérdidas estables. Minar negativos difíciles dentro del pool y etiquetarlos por referencia, sin convertir todos los no juzgados en negativos definitivos. Comparar λ y agregación de pasajes por validación agrupada; ablaciones con pool fijo distinguen información nueva de duplicación. No entrenar con aceptación ni asumir probabilidades independientes.
- [ ] GREEN: mismo pytest y validación por repositorio con dataset/modelos congelados. Si el lineal no mejora RRF fuera de entrenamiento, conservar RRF y registrar el fracaso; no forzar complejidad. Commit propio: `feat: rank code entities with validated evidence features`.

**Paso condicional 8b:** si recall ≥98% pero top‑1 no alcanza 90% en desarrollo, registrar modelo cross-encoder multilingüe local, revisión/licencia/backend y presupuestos 20/40 antes de medir. Crear `src/ken/retrieval/reranking.py`, `tests/retrieval/test_reranking.py`, `experiments/search-engine/compare_rerankers.py`; modificar `service.py` y extra opcional en `pyproject.toml`. RED `test_reranker_never_adds_entities_or_overrides_unique_identity`, `test_timeout_or_missing_model_is_reported_in_profile`, `test_reranker_reorders_only_declared_pool`. GREEN con ese pytest y validación pareada EN/ES. Admitirlo sólo si mejora fuera de repositorio y publicar su coste; si no mejora, retirarlo del camino activo. Un fallback distinto debe evaluarse y reportarse como otro perfil, sin heredar la certificación del principal.

**Checkpoint C:** respuesta presente frente a respuesta bien ordenada. Si aún falta 90%, no abrir la reserva: volver a hipótesis concretas de datos/representación/ranking, conservando intentos. No introducir un agente remoto como atajo.

## Task 9 — Evidencia visible fiel y formato de retorno

**Files:** crear `src/ken/retrieval/presentation.py`, `tests/retrieval/test_presentation.py`; modificar `model.py`, `service.py`; añadir `docs/design/search-response-v2.md` con contrato y ejemplo real verificado.

**Interfaces:** `present(matches, root, request: SearchRequest) -> SearchResponse`; conserva orden, comprueba hash, y produce rangos de entidad y de cada fragmento realmente visible. El presupuesto cuenta el JSON/texto efectivamente expuesto, incluida metadata.

- [ ] RED: `test_late_anchor_is_visible_within_40_lines`; `test_discontinuous_evidence_has_separate_ranges`; `test_budget_does_not_reorder_matches`; `test_concurrent_edit_retries_once_then_marks_stale`; `test_unicode_budget_and_line_ranges_match_content`; `test_large_outline_cannot_replace_matching_member`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_presentation.py -q`; verificar rojo.
- [ ] Implementar selección de ventana alrededor de evidencia, identidad fuera del snippet, hash, truncamiento/omisiones explícitos y reintento acotado. Sin confianza ficticia ni líneas implícitamente omitidas dentro de un rango continuo. `explain` deriva sólo de señales ejecutadas.
- [ ] GREEN: mismo pytest y evaluación estricta de desarrollo sobre las respuestas presentadas, no sólo sobre candidatos internos. Commit propio: `feat: return source-grounded matches with honest evidence ranges`.

## Task 10 — Integrar consumidores preservando contratos

**Files (10a):** modificar `src/ken/search.py`, `src/ken/mcp/server.py`, `src/ken/cli.py`; crear `tests/retrieval/test_public_contracts.py`; extender `tests/test_mcp_schema.py`.

**Interfaces:** adaptar `search_files`/`search_symbols` y `ken_find` al núcleo; formato v2 explícito de evidencia y forma anterior conservada durante migración. `literal=True`, lecturas, outlines y scopes estructurales mantienen sus funciones. Coseno legado separado del nuevo `ranking_score`/versión.

- [ ] RED: `test_legacy_symbol_and_file_shapes_still_work`; `test_mcp_and_cli_return_same_order_and_evidence`; `test_legacy_score_keeps_cosine_semantics`; `test_unmigrated_project_returns_actionable_state`; snapshots de esquema existentes permanecen válidos o cambian aditivamente.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_public_contracts.py tests/test_mcp_schema.py tests/test_search_cli.py -q`; verificar fallos de integración.
- [ ] Implementar adaptadores y perfil experimental explícito; revisar callers reales antes de alterar expectativas de pruebas que exigen coseno puro. No borrar esas pruebas sólo porque el nuevo algoritmo ordena distinto: conservar el modo/contrato legado o versionar la ruptura deliberada.
- [ ] GREEN: mismo comando más `tests/test_mcp_read.py`; medir MCP real en proceso persistente, además de la API. Commit propio: `feat: expose shared retrieval through compatible search adapters`.

**Files (10b):** modificar `src/ken/ranker/channels.py`, `src/ken/ranker/__init__.py`, `src/ken/responsibility/retrieval.py`; crear `tests/retrieval/test_consumers.py`; extender `tests/test_responsibility.py`.

**Interfaces:** canales de contexto consumen `retrieve`; responsabilidad adapta candidatos pero conserva `assess_symbol`/evidencia de sus reasoners. La actividad y memoria siguen en el ranker de contexto, no alteran ocultamente el resultado explícito de búsqueda.

- [ ] RED: `test_consumers_share_candidate_provenance`; `test_memory_context_does_not_change_explicit_search`; `test_responsibility_keeps_module_doc_ownership_and_uncertainty`; `test_context_explain_matches_executed_pipeline`.
- [ ] Ejecutar `.venv/bin/python -m pytest tests/retrieval/test_consumers.py tests/test_responsibility.py tests/ranker -q`; observar fallos previstos.
- [ ] Implementar un adaptador por consumidor y retirar sólo producción duplicada de candidatos. Mantener decisiones de responsabilidad/contexto en sus dueños. GREEN con el mismo comando. Commit propio: `refactor: share retrieval across context and responsibility consumers`.

## Task 11 — Ablaciones, limpieza y coste real

**Files:** crear `experiments/search-engine/ablate.py`, `report.py`, `results/README.md`; completar `signal_audit.csv`; modificar únicamente módulos demostrados redundantes, en commits separados de ≤5 archivos cada uno.

**Interfaces:** consume perfil/dataset y resultados crudos; produce reporte por canal/señal, pool fijo y variable, idioma/propósito/repositorio, latencia API/MCP fría/caliente, indexación incremental, RAM/disco y volumen de evidencia.

- [ ] RED: `test_ablation_report_keeps_dataset_profile_and_pool_hashes` en `tests/bench/test_retrieval.py`; `test_removed_channel_cannot_silently_remain_in_explain` en la suite del consumidor afectado. Ejecutar sus pytest y comprobar rojo.
- [ ] Ejecutar ablaciones de identidad, campos, modelo, agregación, priors de papel, historia/relaciones y fusión. Completar para cada señal: información, correlación, coste, efecto y decisión conservar/retrabajar/retirar. Distinguir frescura, candidato, orden, propietario y evidencia.
- [ ] Eliminar código muerto/redundante sólo con consumidores revisados y resultado reproducible. No eliminar KQL2/memoria/hallazgos por no aportar al benchmark sin historia; no tocar trabajo previo ajeno. Un ranker aprendido rechazado también debe retirarse si no tiene consumidor útil.
- [ ] GREEN: suites afectadas, `.venv/bin/python -m mypy src/ken` comparado con baseline de deuda preexistente y `.venv/bin/python -m pytest -q` al integrar. Fallos anteriores se documentan por separado; los nuevos se resuelven. No sumar suppressions.
- [ ] Commit propio por decisión: `refactor: remove <redundancia demostrada>`; guardar reporte con hashes.

## Task 12 — Gate reservado, revisión y promoción

**Files:** crear `docs/validation/search-engine-top1-2026-10-14/REPORT.md`, `manifest.json`, `gate.json`; guardar salidas crudas y registro de intentos en esa carpeta; modificar selección predeterminada en `src/ken/retrieval/service.py` sólo tras pasar el gate.

**Interfaces:** usa `ken bench --engine retrieval --gate POLICY DATASET --json`, la política congelada de tareas 1–2 y el perfil final de tarea 11. `gate.json` liga resultado con hashes de fuente, modelos, datos, scorer y presupuesto.

- [ ] RED: verificar que un fixture de 89% devuelve exit no cero y que un manifiesto alterado se rechaza antes de medir. Ejecutar `tests/bench` y comprobar esos rechazos.
- [ ] Congelar branch/snapshot y perfil; el evaluador independiente ejecuta baseline/candidato sobre la reserva sin devolver pistas intermedias al optimizador. Publicar gates, intervalos y errores/abstenciones; al abrir fallos, registrar que la reserva quedó consumida.
- [ ] Si algún gate no alcanza 90%, conservar perfil experimental y publicar déficit concreto; iniciar otra iteración con desarrollo ampliado y nueva reserva para la siguiente certificación. No presentar esta tarea como terminada ni activar una etiqueta de 90%.
- [ ] Si pasa: revisión completa de cambios/contratos mediante skill de code review, pruebas de compatibilidad, migración y vuelta al perfil anterior; medir el perfil predeterminado real. Promover sólo ese perfil y ejecutar smoke de API/CLI/MCP sin retocar sus pesos tras aceptación.
- [ ] Commit propio: `feat: promote validated search engine profile`; documentación final con alcance, fallos conocidos, costes y comandos reproducibles. Una ejecución nativa es la propuesta para mantener coherencia entre interfaces; cualquier revisión con agentes deberá seguir la autorización y skill aplicables.

## Cierre y control de alcance

La barra es calidad top‑1 verificada, no cantidad de features. No hacen falta una base vectorial externa, un agente por consulta, una probabilidad inventada ni un nuevo sistema de memoria para completar este plan. Cada expansión debe resolver una clase de fallos observada y superar su control.

Plan auto-revisado: requisitos del diseño asignados a tareas 1–12; contratos compartidos nombrados; cinco riesgos de Review Focus tienen pruebas; reserva y entrenamiento separados; gates no dependen de redondeo; compatibilidad y trabajo anterior preservados. Revisión humana del diseño/plan pendiente antes de implementar, según las skills de diseño y planificación utilizadas.
