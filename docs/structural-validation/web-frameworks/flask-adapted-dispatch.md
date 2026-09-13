# Despacho Flask corregido — IR 1.23.0

La consulta `architecture.dispatch-table` ahora une una variante directa y una
variante `adapted`, ambas escritas en su TOML. El falso negativo de Flask queda
corregido en el alcance revisado. No se agregaron nombres especiales de Flask
al detector ni se ejecutó el proyecto analizado.

## Match revisado

Se escanearon los 24 archivos `src/flask/` del commit
`d73fa1cdcbd8b1465c151db8924ba58b1dd14e35`. El [reporte](flask-ir123.json)
conserva fuentes, hashes del motor, presupuestos y resultados de las seis reglas
modernas. Dispatch Table completa con un match, revisado como TP:

- Clase: `Flask`, `app.py:110`.
- Registro: `App.add_url_rule`, `sansio/app.py:605`; escritura efectiva en línea 661.
- Tabla: `Scaffold.view_functions`, `sansio/scaffold.py:108`.
- Despacho: `Flask.dispatch_request`, `app.py:969`; consulta e invocación en línea 993.
- Adaptador resuelto: `Flask.ensure_sync`, `app.py:1068`, con retorno de
  `async_to_sync(func)` en línea 1078 y del propio `func` en línea 1080.

La [consulta con roles ampliados](flask-adapted-dispatch-witnesses.json) conserva
dos pruebas alternativas correspondientes a esos retornos. Son dos pruebas del
mismo despacho, no dos patrones. `ACCESS_INPUT` conserva el camino
`request → url_rule → endpoint` desde `ctx`, con las asignaciones intermedias.
`INSTANCE_SLOT` relaciona las vistas del campo a través de la herencia simple.
La llamada exterior invoca el resultado del adaptador con los kwargs originales.
No se certifican la equivalencia sync/async ni todos los comportamientos runtime.

## Causas corregidas y pruebas

Además de herencia y claves derivadas, había una pérdida independiente de IR:
`adapter(table[key])` en Python guardaba `table` como argumento porque el lowerer
desenvolvía cualquier campo AST `value`. Ahora solo desenvuelve wrappers de
argumentos. El índice completo llega al adaptador. Se corrigieron también las
gramáticas de índice único de C++/C#/Rust y los campos declarados de JavaScript
que pueden ocultar métodos heredados.

Se agregaron 74 tests: 62 de despacho adaptado y 12 de argumentos indexados.
Despacho cubre Python/JS/TS, aliases, imports entre archivos, overrides, propiedades
y campos que reemplazan métodos, múltiples bases, campos privados, receptores
distintos y adaptadores que descartan o sobrescriben la entrada. Los argumentos
indexados se prueban en ocho lenguajes, además de wrappers nombrados y expandidos.
Las 27 regresiones previas del despacho directo siguen pasando, incluido el
presupuesto de búsqueda ante 150 métodos ajenos. Son pruebas de parsing/IR/query,
no ejecuciones ni compilaciones de los programas fuente.

La suite completa pasa 2.157 tests en 47,69 s; mypy pasa sobre 93 archivos fuente.
Los seis ejemplos KenQL de la guía IR se ejecutan dentro de esa suite. El wheel
se construyó y se verificó que contiene el motor y la consulta actuales.

La [regresión GoF](../multilanguage/ir123-corpus-regression.json) conserva las mismas
fuentes, 53 presencias esperadas en 281 ejemplos y los mismos matches completos.
El TP de Flask pertenece a otra evaluación; no aumenta ese numerador a 54.

## Rendimiento y límites

Una ejecución del escaneo de Flask construyó 6.150 entidades en 1.199,98 ms.
Dispatch Table consumió 2,106 ms, 1.516 estados y 673 filas, completa. Construcción
y consulta se miden por separado. Son observaciones individuales, no percentiles
ni garantías de rendimiento o memoria.

Las relaciones nuevas son parciales: herencia simple resuelta, slots públicos
relativos a una instancia y aliases locales restringidos. No hay MRO múltiple,
análisis general de heap ni identidad global de objetos. Getters y mutaciones
pueden cambiar valores. La evidencia de retorno muestra un posible origen del
handler; otras ramas o APIs de adaptación pueden descartarlo. Pasar una clave
derivada no demuestra que exista en la tabla. Los resultados de las otras reglas
modernas del reporte conservan su estado de revisión previo.

Contrato: [despacho web](../../design/structural/web-dispatch.md).

```sh
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/flask --prefix src/flask/ --collection modern --output /tmp/flask-modern.json
```
