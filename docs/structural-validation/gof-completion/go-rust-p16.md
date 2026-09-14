# P1.6 — Go y Rust en el pase de locales (IR 1.50)

Estado: **entregado**. `structured-locals/3` admite Go y Rust para los cuerpos
medidos; los constructos de ownership que no modela se **rechazan**, no se
adivinan. Esto cierra `facade#module-surface`.
Fecha: 2026-09-13. Base: `d633943`.

## Qué bloqueaba

`return_flow.py` solo admitía `python`, `javascript`, `typescript`, `java` y
`csharp`; cualquier otro lenguaje salía `RETURN_FLOW_STATUS = unsupported` con
`reason = 'language'`. Eso dejaba sin procedencia de valores a Go y Rust, que son
lenguajes objetivo de varias variantes.

## Causa raíz real (no era solo la lista blanca)

Habilitar el lenguaje no alcanzaba. Dos detalles de la gramática de Go dejaban
`region_for` sin región y `call_region` sin camino:

1. **`statement_list`.** En Go el cuerpo es `block` → **`statement_list`** →
   sentencias. `statement_list` no estaba en `containers`, así que `region_for`
   devolvía `None` y toda escritura o retorno se rechazaba como
   `nonlocal-or-nested-write` o `nested-return`.
2. **`expression_list`.** Go envuelve los operandos de `carried := f(key)` en un
   `expression_list`. Sin admitirlo como wrapper, `call_region` devolvía `None`
   y las llamadas de esas expresiones no generaban `ARGUMENT_ORIGIN` — el
   traspaso productor→consumidor se perdía aunque el callable saliera
   `supported`.

Ambos son contenedores/wrappers, no regiones: se agregaron a `containers` y a la
lista de wrappers de `call_region`, respectivamente.

## Contratos medidos antes de admitir cada lenguaje

El plan exige contratos explícitos de asignación múltiple, `move` y referencias, y
prohíbe simular semántica Python. Se midió cada constructo para comprobar que el
resultado es un **rechazo** y no un hecho inventado.

### Go

| Caso | Resultado | Veredicto |
|---|---|---|
| `carried := Fetch(key)` | `supported`, `ARGUMENT_ORIGIN must` | correcto |
| `a, b := Fetch(key)` (un call, dos valores) | `unsupported` (`nonlocal-or-nested-write`) | sin hecho falso |
| `a, b := 1, 2` | `unsupported` | sin hecho falso |
| `value, err := Fetch(key)` + `if err != nil` | `unsupported` | sin hecho falso |
| `a, b = b, a` | `unsupported` | sin hecho falso |

Motivo estructural del rechazo: en una asignación múltiple el target es un
`VALUE` (el `expression_list`), no un `STORAGE`; la comprobación
`targets[op.id] not in locals_by_owner[owner]` lo rechaza sola. No hizo falta
código nuevo para eso: la exclusión ya existía y ahora se aplica a Go.

### Rust

| Caso | Resultado | Veredicto |
|---|---|---|
| `let carried = fetch(key); store(carried)` | `supported`, `must` | correcto |
| `let b = a; store(b)` (`move`) | `supported`, `b` conserva el origen | correcto: un move preserva el valor |
| `let (a, b) = fetch(); store(a + b)` | `unsupported` | sin hecho falso |
| `let mut carried = fetch(); carried = 0` | `supported`, `must` con `0` | correcto |
| `let carried = *boxed; *boxed = 5` | `unsupported` | sin hecho falso |
| `if let Some(v) = opt { store(v) }` | `unsupported` (`control-or-indirect-write`) | sin hecho falso |

`let b = a` es el único caso donde el pase **afirma** algo sobre un move, y lo
afirmado es cierto: el binding `b` recibe el valor que tenía `a`. No se afirma
nada sobre la usabilidad posterior de `a`, que es lo que el borrow checker
gobierna.

## Cambios

En `src/ken/structural/return_flow.py`:

- `containers` incluye `statement_list`.
- Los wrappers admitidos por `call_region` incluyen `expression_list`.
- La lista blanca de lenguajes pasa a
  `{python, javascript, typescript, java, csharp, go, rust}`.

No se agregó lógica específica de Go o Rust: los constructos no modelados siguen
cayendo en las exclusiones existentes. Eso es lo que evita simular Python.

## Efecto en el catálogo

`facade#module-surface` pasa a `ready` con sus cinco lenguajes: la query se mueve
al TOML y la raíz `facade` la incorpora a su unión. Del inventario: **45 ready /
32 design**.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_facade_module_surface.py
.venv/bin/python -m pytest -o addopts='' -q --junitxml=/tmp/ken-p16-junit.xml tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz `facade#module-surface`: **36 passed** (5 lenguajes × positivo,
  renombrado y cinco negativos).
- Suite estructural completa: **6.644 passed, 146 xfailed**, sin fallos
  (baseline previo: 6.631 passed / 146 xfailed; el delta son los tests nuevos).
- `mypy src/ken`: 107 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/return_flow.py` | `0f430cf056e6c6db9eda796c6900e5724f3d8f3b1707068909317092476216f5` |
| `src/ken/structural/patterns/facade.toml` | `8787b46f10912eb0b7a5bb0d102e8d03ad2d27e9ef662f9a1ee9365ec1143117` |
| `tests/structural/test_facade_module_surface.py` | `f9577c4242391784ae89bacf78ca2e2f498b15971bd725b1b0bcae937da42479` |

## Límites declarados

- Go: `(valor, error)` no se modela como par. El caso se **rechaza**; no se
  afirma que el error se propague ni que el valor sea válido.
- Rust: `move`, `borrow` y `deref` no se modelan como tales. Sólo se conserva la
  procedencia del binding en el caso simple; el resto se rechaza.
- C++ sigue fuera (no está en la lista blanca). Su contrato de
  referencias/move/copia es la extensión siguiente de P1.6.
- Nada de esto convierte a Go o Rust en "soportados" en general: la admisión es
  para los cuerpos que el pase ya sabe recorrer, con las mismas exclusiones.

## Siguiente paso

C++ (misma lista blanca más contrato de referencias/move), y después reutilizar
la procedencia de Go/Rust en las variantes que los declaran:
`strategy#static-policy`, `factory-method#contract-slot`,
`singleton#module-shared`, `iterator#callback-iterator`.
