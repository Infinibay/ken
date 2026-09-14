# P1.6 — C++ en el pase de locales (IR 1.51)

Estado: **entregado**. `structured-locals/3` admite C++ para los cuerpos medidos;
la indirección que no modela se **rechaza**. Desbloquea las 25 variantes del
inventario que declaran `cpp`.
Fecha: 2026-09-13. Base: `56da827`.

## Qué bloqueaba

`return_flow.py` solo admitía `python`, `javascript`, `typescript`, `java`,
`csharp`, `go` y `rust`. C++ salía `RETURN_FLOW_STATUS = unsupported` con
`reason = 'language'`, y C++ es el lenguaje con más presencia en el inventario
pendiente: **25 de las 29 variantes `design` lo declaran**.

## Habilitación

Agregar `'cpp'` a la lista blanca fue suficiente para los cuerpos simples, igual
que con Go y Rust. No hizo falta ningún detalle de gramática como el
`statement_list` de Go:

```text
struct Creator { virtual Product create() = 0; };
struct Concrete : Creator { Product create() override { return Product{1}; } };
Product client(Creator& c) { return c.create(); }
```

```text
SUBTYPE_OF   CLASS:Concrete  -> CLASS:Creator
OVERRIDES    Concrete::create -> Creator::create
TARGET       CALL            -> Creator::create     # la llamada del cliente al slot
RETURN_FLOW_STATUS client    -> supported
```

## Contratos medidos antes de habilitar

| Constructo | Resultado | Veredicto |
|---|---|---|
| Llamada virtual y override simples | `supported` | correcto |
| `int& alias = value; alias = 0;` | `unsupported` (`nonlocal-or-nested-write`) | sin hecho falso |
| `int* p = &value; *p = 0;` | `unsupported` | sin hecho falso |
| `static_cast<Item&&>(x)` (move) | `unsupported` (`unknown-binding`) | sin hecho falso |
| `Item second(first)` (constructor de copia) | `unsupported` (`unknown-binding`) | sin hecho falso |
| Herencia múltiple | sin status (no hay cuerpo analizable) | conservador |
| Templates (`Box<int>`) | `supported` | correcto |

No se agregó lógica específica de C++: referencias, punteros, move y copia caen
en las exclusiones existentes. Eso es lo que evita simular semántica Python.

## Límites declarados

- Referencias (`&`), punteros, `move` y constructores de copia **no** se modelan
  como tales: sus cuerpos se rechazan.
- Templates: la sustitución de parámetros de tipo es P5 y no se toca aquí.
- Herencia múltiple: `EFFECTIVE_METHOD`/MRO solo existe para
  python/javascript/typescript; en C++ no se sintetiza una resolución.
- C++ entra en el pase de **locales**, no en un modelo de objetos de C++. La
  semántica de objetos y plantillas sigue siendo P5.

## Validación

- Suite estructural completa con C++ habilitado: **6.671 passed / 146 xfailed**,
  cero regresiones (mismo recuento que sin C++).
- El arreglo del constructor de C++ en `semantic.resolve` (ver
  [`builder#immutable-product`](builder-immutable-product.md)) también se validó
  contra la misma suite, sin regresiones.

## Siguiente paso

Con C++ admitido, las 25 variantes que lo declaran dejan de estar bloqueadas por
*lenguaje* y quedan bloqueadas solo por su capacidad propia (P4 capturas, P5
genéricos/traits, P6 modelos de API). Candidatos inmediatos por dependencias:
`state#state-enum`, `composite#higher-order-traversal`,
`decorator#callable-wrapper`, `prototype#language-copy`.
