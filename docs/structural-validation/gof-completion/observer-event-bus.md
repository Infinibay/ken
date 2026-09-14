# `observer#event-bus` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados
(`python`, `javascript`, `typescript`, `java`, `csharp`, `cpp`, `go`, `rust`).
Fecha: 2026-09-14. Base: IR 1.69.0. **Sin cambio de IR**: la query se escribe con hechos
que ya existían.

## Qué se publica

Un bus con un registro y un **slot de topic** compartidos: el alta inserta el subscriber
bajo ese topic y la publicación recorre el registro bajo **el mismo** topic invocando el
elemento con el payload.

```
subscribe(handler): <registro bajo topic> <- handler                    INSERTED_VALUE
publish(payload):   for handler in <registro bajo topic>: handler(payload)
```

El topic se une **por identidad de entidad**, no comparando cadenas: es el mismo
`STORAGE` en los dos lados. Eso es exactamente lo que el diseño exige ("en un registro
filtrado por topic debe preservarse la relación entre topic del alta y el topic del
publish; que ambas operaciones tengan una cadena no alcanza"), y es lo que rechaza el
negativo `different-topic`, donde el alta y la publicación usan **dos campos** con el
mismo contenido.

## Dos formas de acceso, una sola query

Los lenguajes se reparten la forma de llegar al registro, y la query acepta las dos:

| Forma | Lenguajes | Evidencia |
|---|---|---|
| sintaxis de índice | go, javascript, typescript, csharp, cpp, rust | el acceso lleva `CONTAINER`/`INDEX`, y `INSERTS_INTO` apunta a ese mismo acceso |
| sintaxis de método | python (`dict.setdefault`/`get`), java (`Map.computeIfAbsent`/`get`) | el acceso es una **llamada** con `RECEIVER $registry` y el topic como argumento, unido por `ARGUMENT`→`VALUE`→`LOADED_FROM` |

Java necesita además un tercer camino en el lado de la publicación: liga el bucket
consultado a un **local** antes de iterar, así que el bucket de la iteración se une a la
llamada por `ASSIGNED_FROM`. Las tres alternativas están en la misma query.

Rust entra por la forma de índice: `self.handlers[&self.topic]` usa `Index`/`IndexMut`, y
el topic se resuelve porque IR 1.66 hace que `&slot` denote su slot.

## Un bloqueo registrado que era falso, y cómo se descubrió

La versión anterior de
[`P9-remaining-variants-blockers.md`](P9-remaining-variants-blockers.md) registraba esta
variante como bloqueada: "Java no tiene `operator[]` para `Map`", y de ahí se concluía
que hacía falta **modelar la API de mapa** por lenguaje. Era falso. La forma de método ya
era expresable con hechos existentes; se descubrió al **medir la query** en vez de
razonar sobre el IR. Con eso la variante se cerró sin tocar el motor, que es la quinta de
este trabajo en cerrarse así.

El mismo documento registraba una "colisión de ids de entidad `CALL`" que tampoco existe:
`entity()` incluye el byte final (`{scope}/CALL:{name}@{start}:{end}`), y lo que engaña es
que el `name` de una entidad `CALL` es su byte de inicio. Los volcados que imprimen el
nombre y no el id hacen parecer que dos llamadas anidadas son la misma entidad. Las dos
correcciones quedaron escritas en el registro de bloqueos y en ken.

## Lo que se dejó sin resolver a propósito

* **Entrega y orden.** No se prueba entrega exactamente una vez, ni el orden de los
  subscribers, ni que el callback se invoque de verdad en ejecución.
* **Estabilidad del topic.** Que el campo del topic no se reasigne entre el alta y la
  publicación no se comprueba.
* **Reasignación del registro.** Tampoco que el registro no se reemplace.
* **Un solo bucle.** El vínculo entre el recorrido y la publicación es
  `ITERATES_CALLS` + `HAS_OPERATION` + `ITERATION_INVOKES_VALUE`; si la publicación
  tuviera dos bucles, el contrato no exige que el que invoca sea el que itera el registro.
* **Alcance por lenguaje.** Los ocho lenguajes son los validados; la query no filtra por
  lenguaje.

## Validación

* `tests/structural/test_observer_event_bus.py`: 74 tests. Positivo y renombrado en los
  ocho lenguajes, cinco negativos por lenguaje (`different-topic`, `other-value`,
  `other-registry`, `no-payload`, `no-register`), la consulta raíz `observer` en los ocho,
  una comprobación de que el topic del match es el campo compartido y no el segundo campo
  del fixture, y la comprobación de metadatos.
* Suite estructural completa: **7445 passed / 140 xfailed** (antes: 7371 / 140; los 74
  nuevos son los 74 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`). Ningún test existente cambió de expectativa: la regla raíz `observer`
  gana una rama y los fixtures de las otras cuatro variantes no la satisfacen.
* `mypy src/ken`: limpio (109 ficheros).
* Medición contra el catálogo anterior: los **74** tests fallan, porque la variante era
  `design` y `named_rule` no la registra.
