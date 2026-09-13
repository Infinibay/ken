# Corpus GoF: literales KenQL y Clone derivado de Rust

Escaneo del 12 de septiembre de 2026, con IR 1.12.0. Se ejecutaron las 23
consultas GoF canónicas sobre los mismos 281 ejemplos aislados del corpus v5.
Los hashes de los archivos de entrada coinciden; commits, hashes del motor,
presupuestos y resultados individuales están en `manifest.json` y los JSON por repositorio.

La presencia del patrón etiquetado sube de **52 a 53 de 281**. No se pierde
ninguna presencia anterior. Todas las consultas completaron su enumeración dentro
del presupuesto; no hubo excepciones. Persisten cinco ejemplos con diagnósticos
de parsing. PHP y Swift están inventariados, pero no tienen frontend estructural
compatible y no se cuentan como ejemplos escaneados.

El único cambio de presencia es `creational/prototype/` de
[RefactoringGuru/design-patterns-rust](https://github.com/RefactoringGuru/design-patterns-rust).
La revisión del archivo `main.rs` confirma `Circle` con `#[derive(Clone)]`,
la construcción de `circle1`, `circle1.clone()` y una modificación posterior del
radio de `circle2`. El rol detectado es `Circle`, línea 2. Es un ejemplo válido de
Prototype mediante el mecanismo idiomático de Rust.

La variante consulta ahora `require $unit DERIVE_NAME "Clone";`. Se corrigió la
comparación de extremos entre comillas en KenQL, con 26 tests de cadenas exactas,
escapes, Unicode, composición, restricciones de tipos y recorridos del grafo.
El cambio de cobertura procede de la variante de Clone derivado incorporada
después del escaneo v5; el arreglo de literales permite escribir esa consulta con
la sintaxis de cadenas documentada.

Esta detección no prueba que cualquier macro llamada Clone sea la estándar, ni
que toda clonación produzca una copia profunda. Tampoco 53/281 es una medida de
precisión: las etiquetas upstream no sustituyen la revisión de los matches y
los otros patrones que puedan coexistir. Los falsos positivos y omisiones de los
informes anteriores siguen abiertos salvo los casos explícitamente corregidos.

Reproducción:

```sh
.venv/bin/python examples/bench/validate_pattern_corpus.py \
  --corpus /tmp/ken-pattern-corpus \
  --output /tmp/ken-corpus-v6-recheck
```
