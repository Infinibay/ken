# Producto almacenado de Builder — IR 1.31.0

## Cambio y validación

Builder incorpora `stored-product` en Python, JavaScript, TypeScript, Java, C#
y Rust. Relaciona construcción propia del producto, escritura directa desde un
parámetro en sus miembros y devolución del mismo campo o su copia derivada Rust.
La operación pública `prototype.derived_copy` permite reutilizar esa última
relación con tipo, receptor y llamada correlacionados.

El IR añade `TYPE_HEAD`, `FINAL_MEMBER_INPUT` y `MEMBER_FLOW_STATUS`. Las
anotaciones Rust mantienen su spelling y descriptor genérico al enlazar una
declaración nominal; los parámetros de tipo ligados no se resuelven como clases
globales homónimas. Los inicializadores de structs Rust conservan campos
explícitos/shorthand y modalidad may para atributos, sin expandir struct updates.
Ver [contratos y ejemplos](../../design/structural/stored-product-builder.md).

**218 tests nuevos**: 171 de Builder en seis lenguajes, 24 de tipos/inicializadores
Rust y composición de copias, 20 de transferencias a miembros y tres ejemplos
KenQL de la guía. La suite completa pasa **3.369 tests en 118,61 s**; mypy pasa en
**97 archivos**. Los ejemplos fuente y consultas del capítulo de diseño también
se verificaron mediante parsing y búsqueda. No se ejecutaron los programas objetivo.
El wheel offline incluye todos los módulos y TOML estructurales, comprobados byte
por byte contra los hashes del manifiesto del escaneo.

## Revisión de rust-lang/log

Se repitió el escaneo de los mismos nueve archivos Rust del commit
`8034743dd9d7f7583bd9a670271483d176130911`, con motores
[IR 1.30.0](ir130-rust-log.json) e [IR 1.31.0](ir131-rust-log.json).
La referencia anterior se ejecutó desde el wheel 1.30, evitando comparar sólo
contra el informe histórico 1.3, que mezclaba muchos cambios intermedios.

| Clase / uso | Evidencia revisada | Evaluación |
|---|---|---|
| RecordBuilder | new construye Record; args, metadata, line y los miembros anidados level/target reciben parámetros; build devuelve record.clone(). | TP Builder; cinco testigos de paso. |
| MetadataBuilder | new construye Metadata; level/target modifican sus campos; build devuelve metadata.clone(). | TP Builder; dos testigos de paso. |
| Record | derive(Clone) y llamada desde RecordBuilder.build sobre record. | Uso de copia confirmado; candidato de la variante amplia Prototype. |
| Metadata | derive(Clone) y llamada desde MetadataBuilder.build sobre metadata. | Uso de copia confirmado; candidato de la variante amplia Prototype. |
| KeyValues | derive(Clone), wrapper de referencia prestada y clone dentro de Record.to_builder bajo cfg de kv. | Copia condicionada a configuración; intención GoF no certificada, sin aislamiento por copia profunda. |

Los [testigos ampliados](stored-product-builder-witnesses.json) incluyen pasos,
parámetros, operaciones de escritura, campos, construcciones y finalizaciones.
Fuentes: [RecordBuilder](https://github.com/rust-lang/log/blob/8034743dd9d7f7583bd9a670271483d176130911/src/lib.rs#L1038),
[MetadataBuilder](https://github.com/rust-lang/log/blob/8034743dd9d7f7583bd9a670271483d176130911/src/lib.rs#L1235)
y [copia de KeyValues](https://github.com/rust-lang/log/blob/8034743dd9d7f7583bd9a670271483d176130911/src/lib.rs#L982).

El delta canónico es **dos Builders y tres candidatos Prototype**. Los dos matches
Factory Method anteriores permanecen. No se cuentan otra vez los aliases `gof.*`.
Los tres candidatos Prototype no se suman a los TP de intención confirmados:
reconocer Clone no basta para certificar el propósito GoF del uso.
Los setters que transforman una entrada mediante map o construcciones intermedias
siguen sin ser testigos de esta variante; otros pasos permiten detectar la clase.

## Regresión en corpus y otros proyectos

El [corpus](ir131-corpus-regression.json) conserva **59/281 presencias de la etiqueta
esperada**, con 736 archivos únicos, 745 apariciones por caso y 6.463 consultas.
No cambia ningún match frente a IR 1.30.0; todas las consultas completan.
La mejora de log es evidencia independiente, fuera de esos 281 ejemplos.

[Requests](ir131-requests.json), 19 archivos; [Flask](ir131-flask.json), 24;
[RxJS](ir131-rxjs.json), 123; y [Commons IO](ir131-commons-io.json), 277,
conservan todos sus matches y roles sobre las mismas fuentes. Flask usa la colección
moderna de ocho reglas. Los cinco proyectos tienen cero diagnósticos de parsing
en este alcance y consultas completas dentro del presupuesto del runner.
Esto no representa una reclasificación manual exhaustiva de los resultados previos.

No hay oráculo global de intención: **no se publica precisión, recall ni TN/FN
globales**. Un caso sin etiqueta esperada no es automáticamente un FN confirmado.
Los falsos positivos y ambigüedades previos de Builder/Memento, Adapter y Observer
continúan en el [registro de problemas](problemas.md).

## Rendimiento observado

Sobre el grafo completo de los nueve archivos de log:

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Query Builder canónica | 30 | 1,744 ms | 1,769 ms |
| Variante stored-product | 30 | 1,538 ms | 1,559 ms |
| Query Prototype canónica | 30 | 0,318 ms | 0,390 ms |
| Construcción de vista de consulta | 5 | 165,196 ms | 229,631 ms |

Las queries usan índice y registro ya construidos. Excluyen parseo/enlace, caché
de disco y CLI; la vista se mide aparte. p95 usa rango más cercano y describe
sólo estas muestras. El parseo/enlace de log fue 1.477,15 ms en el escaneo registrado,
con otros trabajos concurrentes; no es una comparación controlada de versiones.
El límite predeterminado de caché continúa en 500 MB decimales configurables.

## Reproducción

```sh
.venv/bin/python -m pytest tests/structural/test_stored_product_builder.py tests/structural/test_rust_nominal_members.py tests/structural/test_member_transfers.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rust-log --prefix src/ --output /tmp/log-ir131.json
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir131
UV_CACHE_DIR=/tmp/ken-uv-cache uv build --wheel --out-dir /tmp/ken-ir131-wheel --offline
```

Los JSON fijan commits, hashes de fuentes/motor, exclusiones y presupuestos. Ni
cfg, macros ni scripts del repositorio se ejecutan. La estructura reconocida no
prueba secuencias de uso válidas, ausencia de alias, pureza de llamadas o typestate.
