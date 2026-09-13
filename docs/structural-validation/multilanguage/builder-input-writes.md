# Configuración final de Builder — IR 1.32.0

## Corrección

`builder#mutable-product` exige ahora una operación con FINAL_MEMBER_INPUT cuyo
destino sea el campo usado para construir el producto retornado. Ya no combina
una asignación histórica del parámetro con una escritura arbitraria al estado.
El pase genérico se extiende a campos directos de instancia, C++ y Go, además
de los miembros anidados y seis gramáticas anteriores.

Go conserva el orden a través de statement_list, pero una asignación múltiple
no se confunde con una escritura escalar. El pase rechaza esos cuerpos cuando
pueden ocultar rebindings. Miembros anidados pueden tener identidad VALUE: el
control de destinos desconocidos preserva los que están acreditados por MEMBER_OF.
Los métodos y funciones C++ que devuelven punteros/referencias conservan su nombre
y parámetros. Ver [contratos y ejemplos](../../design/structural/builder-input-writes.md).

La suite completa pasa **3.490 tests en 124,05 s**; mypy pasa
en **97 archivos**. El wheel offline se verificó byte por byte para el motor y
TOML, y pasó un positivo y un negativo de sobrescritura cargando el paquete
fuera del checkout.

## Matriz controlada de entradas

Se comparó el wheel IR 1.31.0 con el motor actual usando las mismas 72 fuentes
propias: Python, JS, TS, Java, C# y C++, con doce casos por lenguaje. El oráculo
se refiere a configuración final directa, no a intención de diseño.

| Motor | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.31.0 | 29 | 9 | 33 | 1 |
| IR 1.32.0 | 30 | 42 | 0 | 0 |

La [matriz completa](builder-input-write-matrix.json) conserva cada caso y el
hash del fixture. Los negativos incluyen sobrescritura, parámetro reasignado
antes/después, constante, asignación compuesta, rama y salida antes de configurar.
Los positivos incluyen renombrado, retorno fluente, última escritura válida y
una sobrescritura inalcanzable después del retorno. El FN anterior era el método
C++ fluente que perdía su parámetro por el declarador de retorno con puntero.

Estos números no son precisión o recall sobre código externo. Se agregaron
**121 tests**: 107 de escrituras/configuración (incluyendo ocho negativos Go de
asignación múltiple), 13 de declaradores C++ y una consulta ejecutable de la guía.
El pase de escrituras se prueba en ocho lenguajes; la variante completa mutable
por argumento de construcción se prueba en seis. Los programas fuente no se
compilan ni ejecutan como parte de este análisis.

## Corpus y límite de intención

La [regresión](ir132-corpus-regression.json) conserva todos los matches frente a
IR 1.31.0: **59/281 presencias de etiqueta esperada**, 736 archivos únicos,
745 apariciones por caso y 6.463 consultas completas. No se pierde ninguna
coincidencia ni se presenta una caída de cobertura como mejora de precisión.

Document, en `behavioral/memento/document_editor/typescript/`, sigue apareciendo
como Builder y Memento. La revisión del [testigo](builder-input-write-witnesses.json)
confirma `setContent` como paso, la asignación de la línea 22 y `save` como
finalización que construye ConcreteMemento. Esa evidencia satisface la firma
estructural aunque la intención del ejemplo es Memento. **El FP de intención
permanece abierto**; excluir Memento de Builder por etiqueta no lo resolvería.

[Requests](ir132-requests.json), 19 archivos; [Flask](ir132-flask.json), 24;
[RxJS](ir132-rxjs.json), 123; [Commons IO](ir132-commons-io.json), 277; y
[log](ir132-rust-log.json), nueve, conservan sus matches y roles sobre los mismos
commits y hashes. Flask usa las ocho reglas modernas. Esto verifica regresión,
no constituye una reclasificación exhaustiva de todos los candidatos ni un oráculo
negativo para los archivos sin matches.

## Rendimiento observado

Sobre el ejemplo TypeScript document_editor completo:

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Query Builder canónica | 30 | 0,523 ms | 0,596 ms |
| Variante mutable-product | 30 | 0,218 ms | 0,277 ms |
| Query Memento canónica | 30 | 0,497 ms | 0,555 ms |
| Construcción de vista de consulta | 5 | 4,329 ms | 9,105 ms |

Las queries usan índice y registro ya construidos. Excluyen parseo/enlace,
caché de disco y CLI; la vista se mide aparte. p95 usa rango más cercano y
describe sólo estas muestras. No es una comparación controlada de velocidad
entre versiones. Los tiempos de escaneo por proyecto están en los JSON con
la carga concurrente del host; la caché continúa en 500 MB decimales configurables.

## Reproducción y límites

```sh
.venv/bin/python -m pytest tests/structural/test_builder_input_writes.py tests/structural/test_cpp_return_parameters.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir132
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rust-log --prefix src/ --output /tmp/log-ir132.json
```

Se conservan los límites de análisis lineal, aliasing, llamadas con efectos ocultos
y estado entre invocaciones. El enlace de parámetros C++ no resuelve sobrecargas
ni reconstruye todos sus tipos de retorno. Las ramas o asignaciones múltiples
no soportadas no producen un certificado de ausencia de patrón o de bugs.
