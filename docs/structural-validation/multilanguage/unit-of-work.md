# Unit of Work con cambios diferidos — IR 1.24.0

El catálogo incorpora `persistence.unit-of-work`, en su propio TOML, dentro de
`modern` y `persistence`. Hay una variante ejecutable `keyed-change-set` y una
variante transaccional pendiente. La operación pública
`persistence.unit-of-work.keyed_flush` expone helpers, elementos y acciones.

## Positivo revisado

Se analizó el módulo `unit-of-work/src/main/java/` de iluwatar, seis archivos,
sin ejecutar código ni procesar Lombok. El [reporte](unit-of-work-iluwatar.json)
fija commit, fuentes, hashes del motor y presupuesto. El match corresponde a
`ArmsDealer`, con el coordinador `commit` y el campo `weaponDatabase`.

La fuente confirma que `register` obtiene un lote por clave, agrega la entidad
recibida y guarda el lote con esa misma clave. `commit` coordina tres helpers
que recorren lotes del mismo registro y pasan cada entidad al mismo store:

| Helper | Acción y línea de llamada |
|---|---|
| commitInsert | insert, ArmsDealer.java:92 |
| commitModify | modify, ArmsDealer.java:100 |
| commitDelete | delete, ArmsDealer.java:108 |

Los [tres testigos](unit-of-work-witnesses.json) corresponden a un patrón. Es un
TP revisado del ejemplo de cambios diferidos. `WeaponDatabase` contiene stubs:
la muestra no demuestra una base de datos real, atomicidad, commit transaccional
ni rollback. La query tampoco afirma esas propiedades. Un procesador por lotes
con esa misma forma puede ser candidato y necesitar revisión de intención.

## Controles externos y rendimiento

| Alcance | Archivos | Matches UoW | Consulta, ms | Grafo, ms |
|---|---:|---:|---:|---:|
| [iluwatar/unit-of-work](unit-of-work-iluwatar.json) | 6 | 1 | 1,155 | 54,61 |
| [Flask](unit-of-work-flask.json) | 24 | 0 | 0,453 | 1.161,00 |
| [RxJS](unit-of-work-rxjs.json) | 123 | 0 | 0,430 | 1.478,54 |
| [Commons IO](unit-of-work-commons-io.json) | 277 | 0 | 0,679 | 5.096,53 |

Todas las consultas UoW terminaron completas, sin unknowns en el resultado. Los
ceros no son TN certificados ni descartan otras variantes. Los resultados de las
demás reglas modernas se conservan para futuras revisiones. Los tiempos son
observaciones individuales, algunas con otros procesos de validación activos;
no son percentiles, RSS ni medidas de cache. El positivo requirió 406 estados
y 197 filas examinadas.

## Pruebas y límites

80 tests nuevos de Unit of Work cubren Python, JavaScript, TypeScript, Java y C#:
positivo, renombrado, operación pública, PascalCase y negativos por otra entidad,
registro, store, clave, lote guardado, coordinador ausente, una sola acción,
acciones ajenas a persistencia y bindings sobrescritos. Otros 16 tests verifican
productor y paso del elemento por posición en ocho lenguajes. La suite completa
pasa 2.253 tests; mypy pasa y se construyó el wheel. Son pruebas de parsing/IR/query,
no de compilación o ejecución de las fuentes.

La [regresión GoF](ir124-corpus-regression.json) mantiene 53 presencias esperadas
en 281 ejemplos, sin cambios de matches ni consultas incompletas. El TP de Unit
of Work pertenece a una evaluación distinta.

El [escaneo adicional de RxJS con GoF](ir124-rxjs-gof.json) conserva las tres
clases Observer corregidas anteriormente, con consulta completa.

Las relaciones nuevas evitan convertir un conteo de cero escrituras en prueba
de ausencia cuando la cobertura del grafo es abierta. El lote consumido requiere
aliases locales restringidos. `INSERTED_INPUT` e `ITERATION_PASSES_VALUE` excluyen
escrituras explícitas y peligros modelados del binding; no prueban ausencia de
efectos ocultos. El registro conserva asignaciones posibles y la query no garantiza
coincidencia runtime entre claves registradas y consumidas. Transacciones,
colecciones separadas, ORMs, async, rollback y aliases generales siguen pendientes.

Contrato: [Unit of Work](../../design/structural/unit-of-work.md).
