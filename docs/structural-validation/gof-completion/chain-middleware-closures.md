# `chain#middleware-closures` (8 lenguajes) — cerrada, con un residuo medido

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-14. Base: `3a7b624` (IR 1.60.0), **sin cambio de IR**.

## Séptima variante que no necesitó capacidad nueva

`linked-handlers` cubría la forma de objeto: un handler con un sucesor del mismo
contrato y reenvío condicional. Ésta es la forma de cierre, y su contenido entero es
que **capturar `next` no alcanza**: `decorator#callable-wrapper` ya cubre un wrapper
que captura y siempre reenvía. Lo que convierte al cierre en un eslabón de cadena es
que el reenvío esté **guardado por una rama**, de modo que el handler pueda además
devolver sin reenviar.

Todo estaba ya en el grafo:

| Necesidad | Hecho |
|---|---|
| La fábrica recibe el siguiente handler | `HAS_PARAMETER` |
| El handler lo captura | `CAPTURES` |
| Hay una decisión | `HAS_OPERATION` + `operation(kind: branch)` |
| La rama tiene dos desenlaces distintos | dos `CFG_NEXT` + `different` |
| Un desenlace devuelve el resultado del delegado | `RETURN_OPERAND` o `SYNTAX_NODE` |
| El otro devuelve otra cosa | `RETURN_OPERAND` + `different` |

## La expresión de cola de Rust

Siete lenguajes escriben el desenlace que continúa como un `return` explícito, así que
`RETURN_OPERAND` liga el `return` con la llamada al delegado. Rust no: el idioma es la
**expresión de cola**,

```rust
move |request: &str| {
    if request.is_empty() { return "denied".to_string(); }
    next(request)          // sin `return`
}
```

donde la llamada *es* el sucesor de la rama, no el operando de un `return`. Se midió
que `RETURNS` del cierre ya incluye esa llamada, pero también incluye la del otro
ramal, así que no discrimina. Lo que sí la ata a la rama es `SYNTAX_NODE`: la entidad
`CALL` es el nodo sintáctico de ese sucesor concreto. La query acepta las dos grafías:

```kenql
any { require $continuing RETURN_OPERAND $delegate; }
or { require $delegate SYNTAX_NODE $continuing; }
```

## Residuo medido, y por qué queda ejecutable

**Una rama que delega en AMBOS desenlaces sigue matcheando.** Ese handler nunca
termina: todos sus caminos reenvían, así que estructuralmente es un wrapper y no un
eslabón con decisión real.

Lo medí en vez de suponerlo: el fixture de doble delegación da **2 matches**. La causa
está acotada y es de KenQL, no de la query:

- expresar «este ramal no delega» necesita **cardinalidad exacta**
  (`count distinct $call = 1 { … }`) o **ausencia acotada**
  (`not exists { … } within callable($wrapped)`);
- ambas exigen que el bloque sea *cerrado*, y `closed()` (kenql.py:405) requiere la
  capacidad `complete:<sujeto>:<relación>`;
- la única que se declara es `complete:<callable>:HAS_PARAMETER`
  (kenql.py:616-619, solo Python y sin diagnósticos).

Sin clausura, `count = 1` y `not exists` producen incertidumbre y el modo `strict` las
descarta. Verificado: `count >= 1` matchea y `count = 1` no; el bloque `not exists`
devuelve 0.

Por eso el residuo se registra como `xfail(strict=True)` en
`tests/structural/test_chain_middleware_closures.py`, con la capacidad que falta
nombrada en el `reason`. Cuando aterrice una completitud para `HAS_CALL`, el marcador
pasará a `XPASS(strict)` y la suite pedirá que se retire: el hueco queda así
ejecutable, no escondido en prosa.

Se descartó cerrarlo exigiendo que el desenlace que termina devuelva un valor **no
llamada**: eso habría rechazado el middleware canónico que cortocircuita con una
respuesta calculada (`return res.status(403).send("denied")`). Preferí un falso
positivo acotado y declarado a un falso negativo sobre código real.

## Negativos cubiertos

22 pruebas en `tests/structural/test_chain_middleware_closures.py`: 8 positivos (uno
por lenguaje), 8 negativos de wrapper incondicional (uno por lenguaje), 4 negativos
propios de Python y 2 comprobaciones del contrato publicado.

| Negativo | Por qué se rechaza |
|---|---|
| wrapper incondicional, en los 8 lenguajes | sin rama no hay eslabón: es `decorator#callable-wrapper` |
| handler que nunca reenvía | no hay llamada al delegado |
| handler que reenvía pero no devuelve su resultado | `RETURN_OPERAND` no liga el delegado |
| handler que no captura `next` | falta `CAPTURES` |
| **(xfail) rama que delega en ambos desenlaces** | residuo medido: falta clausura sobre `HAS_CALL` |

## Límites declarados

`query_claim` no prueba manejo exclusivo, preservación de la request ni topología de la
cadena. Tampoco prueba que exista un camino que termine: prueba que el reenvío está
**guardado por una rama**, que es lo que la ficha pide distinguir del pipeline
incondicional.

## Validación

`tests/structural/` completo, sin regresiones, más las 22 pruebas nuevas (1 `xfail`
estricto). `mypy src/ken` limpio. Sin bump de `IR_VERSION`: el grafo no cambia.
