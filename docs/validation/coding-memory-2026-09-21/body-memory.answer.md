Voy a consultar la memoria señalada y el código implicado para evaluar la propuesta sin modificar archivos ni memorias.
Hoy **no es válida como optimización general**: conserva el entorno completo hasta disponer de un contrato exhaustivo de dependencias.

La evidencia es concreta:

- [`member_place`](/private/tmp/ken-coding-memory-4n2epo1i/body-memory/src/ken/kql2/body.py:1111) recorre `current.values()` para resolver miembros literales; puede necesitar declaraciones ligadas a roles ausentes de `_inputs`.
- [`SourceExecutor.match`](/private/tmp/ken-coding-memory-4n2epo1i/body-memory/src/ken/kql2/source_execution.py:197) recoge roles, alias y expresiones, pero omite `Clause.name`. Actualmente utiliza `_inputs` para memoización y entrega el entorno completo al motor.
- La memoria registra **109 regresiones por pérdida de positivos**, corregidas al retirar esa proyección. Sus dependencias declaradas siguen sin cambios; eso no certifica sus supuestos ni cobertura transitiva.

Antes de implementarla, recomiendo una prueba diferencial: evaluar `$obj.campo` con la declaración de `campo` ligada a un rol externo ausente de `_inputs`, usando entorno completo y proyectado, con cachés independientes vacías. Comparar coincidencias, roles de salida y estados `Unknown`. Añadir cobertura de referencias en `Clause.name` y ejecutar `tests/kql2/test_body_field_initializer.py`. Auditar por separado la clave de memoización: su uso actual no demuestra que capture todas las dependencias.