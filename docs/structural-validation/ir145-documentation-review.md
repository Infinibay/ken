# Revisión de documentación: IR 1.45.0

Revisión del 13 de septiembre de 2026 sobre el motor y catálogo de
[IR 1.45.0](multilanguage/ir145-checks.json). Esta actualización modifica las
guías, el diseño y tests de documentación; los hashes de todos los módulos y
TOML del motor coinciden con esa auditoría. No cambia el esquema ni la semántica
del IR, por lo que no requiere invalidar la caché o incrementar su versión.

Correcciones:

- KenQL conservaba el conteo de nueve reglas modernas/web: el catálogo actual
  contiene diez. Se verificaron también 23 conceptos GoF, 44 variantes ejecutables,
  33 variantes de diseño y nueve operaciones públicas.
- Las notas de IR 1.43–1.45 estaban debajo de caché/distribución; ahora forman
  parte de la explicación del IR y su precisión.
- El diseño de campos incluía `unsupported` como modalidad de inicialización.
  El código sólo emite `explicit`, `implicit` y `absent`; el estado de análisis
  se expresa por separado.
- La referencia ahora especifica extremos, atributos y alcance de las tres
  relaciones de inicialización. Explica parámetros genéricos léxicos, operandos
  fuente frente a resultados de llamadas y tipo declarado frente a tipo inferido.
- Se documentó cómo mantener las propuestas, contratos implementados y ejemplos
  ejecutables sincronizados sin reescribir resultados históricos.

Verificación realizada:

- **194 tests pasan en 5,66 s**: documentación IR, documentación KenQL, valores
  iniciales de campos y Singleton con defaults implícitos.
- Diez tests nuevos ejecutan las cinco consultas de la guía KenQL con testigos y
  controles sin la evidencia requerida. Cargan la dependencia TOML de la propia
  guía, incluida su composición mediante `match`.
- Las 43 consultas de ambas guías parsean y se ejecutan en sus tests: 38 en IR y
  cinco en KenQL. Se comprobó también el ejemplo Python de la API.
- Los ocho fragmentos de la tabla de inicialización coinciden con el modo,
  estado y valor extraídos por el motor. Se verificó que FIELD_INITIAL_VALUE
  conserva un operando CALL en la vista query y que RESULT permite seguir su valor.
- Se comprobaron enlaces locales y anclas de las cuatro guías modificadas.

Comando de tests:

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_documented_ir_queries.py \
  tests/structural/test_documented_kenql_queries.py \
  tests/structural/test_field_initial_values.py \
  tests/structural/test_implicit_lazy_fields.py
```

La suite completa de 5.709 tests y las mediciones de rendimiento siguen siendo
el resultado histórico de la auditoría enlazada. No se repitieron en esta revisión
de documentación; los diez tests nuevos no están incluidos en aquel total.
