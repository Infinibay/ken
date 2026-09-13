# Prototype: copia de campos y objetos devueltos — IR 1.26.0

## Resultado revisado

Se corrigen dos falsos negativos observados: `PreparedRequest.copy` en Requests
(Python) y `MolecularSimulation.clone` en across-languages (TypeScript). El nuevo
TOML `prototype#field-copy` exige una construcción del mismo tipo, una copia
directa de un campo al campo homónimo y retorno de ese objeto. La evidencia de
última escritura se conserva por asignación y rama; no se une por nombre de clase.

En Requests, la construcción está en models.py:457, el retorno en 465 y las cinco
copias directas corresponden a method:458, url:459, body:462, hooks:463 y
_body_position:464. Los RHS de headers y cookies permanecen opacos y no cuentan
como copias directas. Hay **un TP revisado a nivel de clase**, con cinco testigos,
no cinco patrones diferentes. El [escaneo completo](prototype-field-copy-requests.json)
mantiene Command en cero; los [testigos y mediciones](prototype-field-copy-witnesses.json)
incluyen commit, hashes de fuentes y motor.

En TypeScript, clone construye MolecularSimulation en la línea 66, comparte
_precomputedStates desde la instancia original en 69 y devuelve clone en 73.
Es **otro TP revisado**; compartir ese array muestra por qué no se debe afirmar
copia profunda. El [reporte por variante](prototype-field-copy-typescript.json)
confirma la nueva firma. La variante anterior `explicit-copy` todavía no reconoce
esta forma de retorno por local: compara el resultado de construcción con el
valor retornado de la vista query, que aquí es una lectura del binding.

## Causas y correcciones

- El pase de retornos rechazaba toda escritura a miembros. Ahora admite los
  miembros simples de bindings locales y mantiene estados separados por rama.
- Requests incluye un ternario en headers; se permite ese RHS opaco sin atribuirle
  el valor de una rama ni rechazar las demás escrituras del método.
- Las anotaciones Python de campos sin inicializador se clasificaban como
  almacenamiento estático. Se distingue una anotación de una asignación de clase;
  un valor explícito previo no se pierde y se conserva el spelling ClassVar.
- Un local llamado clone/count podía resolverse al método/campo homónimo de la
  clase. Las declaraciones locales ahora crean un binding del callable. Esto
  conserva la identidad necesaria en el ejemplo TypeScript real.

Los usos opacos y escapes invalidan conservadoramente la evidencia de campos,
incluyendo contenedores y aliases. Una escritura posterior mata la copia anterior.
Ramas terminadas no aportan estado al retorno posterior. Las alternativas que sólo
ocurren en algunas ramas se etiquetan may y requieren modo possible. Los tests
también evitan cruzar la copia de un objeto en una rama con otro objeto retornado.

## Regresión y límites de las cifras

Se agregan **195 tests** en Python, JavaScript, TypeScript, Java y C#: positivos,
renombrado, aliases, reasignaciones, campos homónimos, tipo distinto, publicación,
ternarios, ramas y presupuestos. Son pruebas de parsing/IR/query; no ejecutan ni
compilan los programas de muestra. Se agrega también un ejemplo KenQL al test
de documentación.

La suite completa pasa **2.518 tests** en 68,01 s. Mypy pasa en 93 archivos;
el wheel se construye offline y sus archivos estructurales se comparan byte por
byte con las fuentes verificadas. Estos checks no certifican todos los idiomas
ni todas las variantes GoF pendientes.

El [corpus repetido](ir126-corpus-regression.json) pasa de **53 a 54 presencias
esperadas en 281 ejemplos**, con los mismos archivos y commits. El único cambio
de coincidencias es MolecularSimulation; no hay pérdidas ni consultas incompletas.
Estas presencias no son recall global y el corpus no es una matriz exhaustiva de
TP/TN/FP/FN. El TP de Requests se cuenta fuera de esos 281 ejemplos.

Los controles sobre [Flask](ir126-flask-modern.json), 24 archivos, y
[RxJS](ir126-rxjs-gof.json), 123 archivos, conservan todas sus coincidencias y roles
respecto de los reportes anteriores con las mismas fuentes. Esto es evidencia de
regresión, no una nueva auditoría de intención de todos esos matches.

## Rendimiento observado

Requests, 19 archivos; mediciones locales sin ejecutar el código analizado:

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Parseo y enlace sin caché, bytes ya leídos | 5 | 1.055,422 ms | 1.219,919 ms |
| Query field-copy, índice y registro ya construidos | 30 | 0,204 ms | 0,302 ms |

Construir la vista de consulta tomó 241,247 ms en una observación separada.
La medición de la query no incluye esa preparación. El p95 usa rango más cercano
y describe esta muestra, no una garantía de latencia. El corpus tuvo mediana por
caso de 33,26 ms frente a 33,64 ms previamente; las ejecuciones tuvieron distinta
carga del host y no permiten atribuir una mejora de rendimiento al cambio.

## Trabajo pendiente

Copias mediante temporales de valores, setters/descriptors, heap general,
factibilidad de caminos, loops y retornos implícitos necesitan modelos adicionales.
La nueva variante no corrige por sí sola toda la imprecisión de `explicit-copy`.
Los FP conocidos de otras formas de Prototype y Builder siguen en sus auditorías;
no se deduce precisión perfecta de estos dos casos corregidos.

Reproducción del escaneo:

```sh
uv run python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/requests --prefix src/requests/ --output /tmp/requests-ir126.json
uv run python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir126
uv run pytest tests/structural/test_prototype_field_copy.py tests/structural/test_documented_ir_queries.py
```
