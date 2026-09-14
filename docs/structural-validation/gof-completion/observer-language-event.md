# `observer#language-event` (C#) — cerrada (IR 1.51)

Estado: **cerrada**. La variante es `ready` en su único lenguaje declarado.
Fecha: 2026-09-13. Base: `7910fe7`.

## Punto de partida

El diagnóstico de la ronda anterior dejó tres brechas medidas. Las tres se
cerraron y la variante se promovió.

## Las tres brechas y su corrección

### 1. El `event` no se marcaba

`event_field_declaration` se procesaba como un campo corriente, así que `+=`
sobre un evento era indistinguible de un `+=` aritmético o de un `+=` sobre un
campo delegado. Ahora el frontend marca la declaración con
`class DECLARES_EVENT storage` y `attrs['event'] = True` en el `STORAGE`; el
`HAS_FIELD` existente se conserva para no romper a los consumidores actuales.

**Accessors personalizados quedan fuera a propósito.** Un `event` con
`add { }` / `remove { }` es un nodo distinto (`event_declaration`, no
`event_field_declaration`) y **no** se marca: su semántica no se conoce, así que
no se emite ningún hecho de registro. El test lo verifica.

### 2. No había resolución miembro→campo

`publisher.Changed` producía `MEMBER:Changed` con `MEMBER_OF
PARAMETER:publisher`, y el parámetro ya tenía `type='Publisher'`, pero nada lo
unía con `STORAGE:Changed` de `CLASS:Publisher`. El pase nuevo emite
`MEMBER_DECLARATION(member → campo)` cuando el receptor tiene un tipo nominal
**inequívoco**: la cadena de tipo debe ser un nombre simple y debe resolver a una
sola clase o interfaz que declare ese miembro. Un receptor estructural, genérico
o ambiguo no produce hecho.

Es una capacidad general, no específica de eventos: sirve también a
`observer#event-bus`, `mediator` y `singleton#module-shared`.

### 3. La invocación no se ligaba al evento

`Changed?.Invoke(payload)` —la forma idiomática— quedaba como
`CALLEE_NAME = 'Changed?.Invoke'` sin receptor. El frontend ahora trata el
`conditional_access_expression` como callee de miembro: su primer hijo es el
receptor y el `member_binding_expression` da el nombre. `Changed?.Invoke(x)`
queda igual que `Changed.Invoke(x)`.

## Contrato publicado

```kenql
query observer {
 require $unit DECLARES_EVENT $event;
 require $attach ADDS_HANDLER $event;
 require $detach REMOVES_HANDLER $event;
 different $attach $detach;
 require $raise HAS_CALL $call;
 require $call RAISES_EVENT $event;
 emit $unit, $event, $attach, $detach, $raise;
}
```

Afirma: el tipo declara un `event` de C#, un método registra un handler, **otro**
lo da de baja y **otro** lo emite, todo sobre **el mismo almacenamiento**. El
fixture registra dos handlers y da de baja uno.

**Lo que no prueba** (declarado en `query_claim`): la correlación
payload→parámetro del handler, el orden temporal, ni la unicidad de entrega. La
correlación payload→parámetro requiere contratos callable (P4) y sería un
refinamiento más fuerte, no un requisito de la raíz.

## Positivo y negativos

Positivo (1 match, con los tres roles distintos):

```text
$unit    CLASS:Publisher
$event   STORAGE:Changed
$attach  CALLABLE:Attach@82      # registra `first` y `second`
$detach  CALLABLE:Detach@205     # da de baja uno
$raise   CALLABLE:Raise@273      # emite con payload
```

Negativos, todos sin match:

| Caso | Por qué |
|---|---|
| Campo delegado normal (`Action<int> Plain`) con `+=`/`-=` | no es `event`: no hay `DECLARES_EVENT` ni hechos de registro |
| `event` con accessors personalizados | semántica desconocida: no se marca |
| `event` declarado pero nunca emitido | falta la emisión |
| Registro en un evento y baja/emisión en **otro** | no comparten almacenamiento |
| Registro desde **otra clase** | positivo: resuelve por tipo nominal del receptor |

## Archivos

- `src/ken/structural/frontend.py`: marca de `event_field_declaration`; callee
  `conditional_access_expression`.
- `src/ken/structural/events.py`: pase nuevo (`MEMBER_DECLARATION`,
  `ADDS_HANDLER`, `REMOVES_HANDLER`, `RAISES_EVENT`).
- `src/ken/structural/semantic.py`: registro del pase.
- `src/ken/structural/kenql.py`: relaciones nuevas.
- `src/ken/structural/model.py`: `IR_VERSION` 1.50.0 → 1.51.0.
- `src/ken/structural/patterns/observer.toml`: variante `ready` con query; raíz
  con unión.
- `tests/structural/test_observer_language_event.py`: 8 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_observer_language_event.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q --junitxml=/tmp/ken-observer-junit.xml tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva + catálogo: **272 passed**.
- Suite estructural completa: **6.653 passed, 146 xfailed**, sin fallos
  (baseline previo: 6.644 / 146; el delta son los tests nuevos).
- `mypy src/ken`: 108 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/events.py` | `ff38b9a5b420127d7df7a39d071c6acdd7bc91d9660e69278c9ee6a020e4833a` |
| `src/ken/structural/frontend.py` | `87bb1fa6fe8f87c084684dc9612863f9a0a18f3528fc5b722007597d2fbf6363` |
| `src/ken/structural/patterns/observer.toml` | `3fdc19453608aaf13f36130f8e29ad1e3e1e2e0af6092c8f2b76fa6ff76aa421` |
| `tests/structural/test_observer_language_event.py` | `561f834f396b15161639f1a2071de9cd9ad86fc7b4f1066ea72c58d8b07f25f7` |

## Inventario

**46 ready / 31 design** (antes 45 / 32).

## Siguiente paso

`observer#event-bus` (ocho lenguajes) reutiliza `MEMBER_DECLARATION` pero necesita
una identidad de bus/topic resuelta, que es un modelo de API de P6. La capacidad
de resolución nominal ya está; el siguiente cuello de botella compartido es el
modelo de bus (sirve también a `mediator#message-coordination`).
