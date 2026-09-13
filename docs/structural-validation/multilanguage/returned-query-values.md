# Orígenes de retorno disponibles para las queries — IR 1.27.0

## Cambio comprobado

El pase de retornos ya sabía que `local = Product(...); return local` devuelve
la construcción. La vista KenQL ignoraba ese resultado y exponía sólo un valor
leído de local. Por eso queries que unían RETURNS_VALUE con RESULT no podían
reconocer la forma a través de aliases, aunque el IR tuviera el origen correcto.

Ahora RETURNS_VALUE usa RETURN_ORIGIN en callables con retorno soportado y
preserva la operación de retorno, evidencia y modalidad. Orígenes sustituidos y
retornos explícitos inalcanzables no participan. El resto conserva la proyección
sintáctica previa con basis=syntax; las consultas pueden exigir basis=flow.
No cambian los hechos RETURNS de la vista fuente ni se convierten todas las
lecturas y argumentos en flujo preciso.

**115 tests nuevos** ejercitan Python/JavaScript/TypeScript/Java/C#, tanto en una
query genérica como en Prototype y Builder: retornos directos, locales, aliases,
sobrescrituras, retornos inalcanzables, ramas may, evidencia por ocurrencia,
parámetros, fallback y round-trip serializado. Un ejemplo nuevo de la guía IR
también se ejecuta. La suite completa pasa **2.634 tests en 72,74 s**; mypy pasa
en 93 archivos. El wheel construido offline coincide byte por byte con los
archivos estructurales cuyo hash registra el corpus.

## Revisión externa

La variante explicit-copy ahora reconoce MolecularSimulation.clone (TypeScript),
que ya se reconocía con field-copy desde IR 1.26. Hay dos pruebas válidas del
mismo patrón en la misma clase, **no un TP nuevo a nivel de clase**.
Los [testigos por variante](returned-query-values-witnesses.json) permiten revisar
ambas explicaciones.

El [corpus repetido](ir127-corpus-regression.json) conserva **54 presencias
esperadas en 281 ejemplos**, con los mismos archivos/commits y ninguna consulta
incompleta. Hay un match adicional: Builder sobre Document.save, en el ejemplo
Memento TypeScript. **Se revisó como falso positivo de intención**, no se contó
como avance de cobertura ni se ocultó del reporte.

Document.setContent configura el campo content y save construye ConcreteMemento
con él. Esa evidencia de flujo es correcta, pero la firma Builder también acepta
esta proyección de estado. Document.restore recibe IMemento y llama getState;
Memento aún no reconoce ese protocolo basado en un getter y un contrato.
La [propuesta de Memento con accessors](../../design/structural/memento-accessors.md)
describe el próximo trabajo. Excluir todos los Mementos de Builder sería incorrecto:
un Builder puede ofrecer también snapshots, por lo que hay que mejorar la
evidencia de uso y documentar las ambigüedades.

[Requests](ir127-requests.json), 19 archivos; [Flask](ir127-flask.json), 24; y
[RxJS](ir127-rxjs.json), 123, conservan exactamente coincidencias y roles respecto
de IR 1.26 sobre las mismas fuentes. Esto es un control de regresión, no una
revisión nueva de intención de todos sus matches.

El [escaneo de Commons IO](ir127-commons-io.json) conserva el FP Prototype de
FilePart.rollOver: el nuevo objeto representa el bloque anterior. Su cuerpo
contiene throws y no entra en el pase de retornos soportado; sigue usando la
proyección sintáctica. Corregir la identidad del retorno no distingue por sí solo
una copia de un sucesor que comparte algunos campos. El problema JAVA-02 sigue
abierto en el [registro de problemas](problemas.md).

## Rendimiento observado

Sobre el grafo de Requests ya enlazado:

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Construcción de la vista de consulta | 5 | 229,894 ms | 291,298 ms |
| Query Prototype completa sobre índice y registro construidos | 30 | 1,053 ms | 1,137 ms |

Estas mediciones excluyen parseo, enlace, caché de disco y overhead del CLI.
El p95 usa rango más cercano y sólo describe la muestra. La query Prototype
completa incluye sus tres variantes; no es comparable directamente con medir
sólo field-copy en el informe anterior.

Los [datos de medición](returned-query-values-witnesses.json) incluyen los hashes
del motor, fuentes, commits y resultados. No se publica una precisión/recall global
ni se interpretan repositorios sin matches como verdaderos negativos certificados.

```sh
uv run pytest tests/structural/test_returned_query_values.py tests/structural/test_documented_ir_queries.py
uv run python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir127
uv run python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/commons-io --prefix src/main/java/ --output /tmp/commons-ir127.json
```
