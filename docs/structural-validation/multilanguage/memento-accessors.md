# Memento con getters y bindings por llamada — IR 1.28.0

## Cambio comprobado

La nueva variante `accessor-snapshot` exige una ida y vuelta del estado:
originador → argumento del constructor → parámetro → campo del snapshot → getter
→ llamada al restaurar → campo original. Los bindings conservan la ocurrencia de
llamada y argumento, evitando mezclar entradas de construcciones diferentes.

Los pases `explicit-arguments/1` y `linear-fields/1` son genéricos. Sus
[contratos y límites](../../design/structural/call-bindings.md) incluyen defaults,
nombrados, variádicos, overloads, reasignaciones y efectos no modelados. La
[variante](../../design/structural/memento-accessors.md) cubre Python/JS/TS/Java/C#
con tipo concreto, contrato nominal o evidencia de caller para parámetros sin tipo.
También se corrigieron los defaults C# no etiquetados por Tree-sitter y el enlace
de interfaces TypeScript exportadas entre archivos. No se afirma resolución
completa de exports/reexports ni de sobrecargas.

**188 tests nuevos**: 35 de bindings, 152 de Memento y un ejemplo ejecutable de
la guía IR. Incluyen cinco lenguajes, renombrado, posiciones distintas, campos
incorrectos, constantes, valores reemplazados, receptor escapado, ausencia de uso,
imports, defaults, argumentos inválidos/no soportados y serialización.
La suite completa pasa **2.822 tests**; mypy pasa en **95 archivos**. El wheel
construido offline contiene los archivos estructurales verificados byte por byte
contra los hashes del manifiesto. Los programas analizados no se ejecutaron.

## Revisión de los matches nuevos

El [corpus repetido](ir128-corpus-regression.json) usa los mismos commits y fuentes
que IR 1.27: **281 casos, 736 archivos únicos (745 apariciones por caso), 6.463
consultas GoF**. Pasa de **54 a 57 casos con presencia de la etiqueta esperada**,
sin pérdidas ni consultas incompletas. Cuatro casos cambian sus matches:

| Caso TypeScript de across-languages | Cambio | Revisión |
|---|---|---|
| Memento / document_editor | Memento sobre Document | TP revisado: save recibe content en ConcreteMemento; constructor lo guarda en state; getState lo devuelve por IMemento; restore escribe content. |
| Strategy / payment_processing | Strategy sobre PaymentContext | TP revisado: IPaymentStrategy se recibe/almacena y processPayment delega pay(amount); setStrategy permite sustituirlo. |
| Visitor / code_analyzer | Visitor sobre cinco tipos de nodo | Cinco roles TP revisados: accept pasa `this` al visit correspondiente del contrato importado. Se cuenta como un caso esperado recuperado. |
| State / order_processing | Strategy sobre Order; State sigue ausente | Ambigüedad estructural y FP respecto de intención: delegación a IOrderState comparte forma con Strategy, pero estados concretos provocan transiciones mediante order.setState. El State esperado es un FN revisado. |

Los cinco nodos Visitor son AssignmentStatementNode, ExpressionStatementNode,
FunctionDefinitionNode, IfStatementNode y VariableDeclarationNode. El contrato
Visitor y ComplexityVisitor confirman las operaciones por tipo de elemento.
Los incrementos de Strategy y Visitor provienen del enlace de interfaces exportadas;
no se atribuyen a la nueva query Memento.

Los [testigos de Memento](memento-accessors-witnesses.json) incluyen roles internos,
consulta, evidencia, hashes de fuentes y motor. El commit de across-languages es
`efd075de92e42099e8ae24fc274dc0e7b86ba2f9`.

**El FP Builder sobre Document sigue presente.** Detectar Memento no lo elimina
ni justifica excluir automáticamente todo snapshot de Builder. El registro de
[problemas](problemas.md) conserva esta ambigüedad y la nueva de State/Strategy.
La cifra 57/281 es presencia de etiquetas, no una medición de precisión o recall
universal. Los 224 casos restantes no son automáticamente 224 FN confirmados y
los repositorios sin matches no son verdaderos negativos certificados.

## Regresión en proyectos reales

[Requests](ir128-requests.json), 19 archivos; [Flask](ir128-flask.json), 24;
[RxJS](ir128-rxjs.json), 123; y [Commons IO](ir128-commons-io.json), 277,
conservan exactamente matches y roles de IR 1.27, sobre fuentes idénticas y sin
consultas incompletas. Flask usa la colección modern; los demás, GoF y controles
sintácticos del runner. Esto es control de regresión, no una nueva clasificación
manual de todos los matches. El FP Prototype FilePart.rollOver de Commons IO
sigue pendiente.

## Rendimiento observado

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Query Memento completa, grafo del ejemplo TypeScript ya indexado | 30 | 0,470 ms | 0,548 ms |
| Construcción de vista de consulta de Requests | 5 | 226,779 ms | 324,175 ms |
| Query Prototype completa de Requests, índice y registro construidos | 30 | 1,092 ms | 1,130 ms |

Las queries se miden sobre índice y registro de dependencias ya construidos.
Excluyen parseo/enlace, caché de disco y overhead del CLI; no representan el coste
de un escaneo completo. El p95 usa rango más cercano y describe sólo esta muestra.
Los tiempos de los runners externos se conservan como observaciones de corridas
independientes con carga del host variable, no como prueba de mejora de rendimiento.
El [JSON de testigos](memento-accessors-witnesses.json) conserva estas mediciones.

## Reproducción

```sh
.venv/bin/python -m pytest tests/structural/test_call_bindings.py tests/structural/test_memento_accessors.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir128
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/requests --prefix src/requests/ --output /tmp/requests-ir128.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/flask --prefix src/flask/ --collection modern --output /tmp/flask-ir128.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rxjs --prefix packages/rxjs/src/ --exclude-glob '*.spec.ts' --exclude-glob '*/testing/*' --output /tmp/rxjs-ir128.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/commons-io --prefix src/main/java/ --output /tmp/commons-ir128.json
```
