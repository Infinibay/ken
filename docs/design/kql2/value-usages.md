# Valores capturados y sus usos

Implementación inicial, IR 1.85. Complementa el
[contrato de BODY](saved-body-execution.md).

## Capturar no significa exigir una variable

```kql2
let $result = call $load {};
```

`$result` es un valor interno de la consulta. Identifica lo producido por una
ocurrencia de llamada, no una variable que deba existir en el código analizado.
Puede provenir de `temporary = load()` o de la llamada anidada en
`consume(load())`. Dos invocaciones de `load()` no son intercambiables.

El matcher de condiciones también admite capturar la llamada inline antes de
comprobar cómo gobierna una salida. Cuando el patrón compara con `false`, una
negación fuente sólo se considera equivalente si hay evidencia de resultado
booleano. No se confunden falsedad lógica, null y el booleano false.

## Seleccionar consumidores

```kql2
language "kql/2";
module examples.value_usages;

pattern Produced(out Value $result) {
    callable $load { name: "load"; }
    callable $work {
        body { let $result = call $load {}; }
    }
}

query arguments {
    use Produced(result: $value);
    usages of $value as $use {
        kind: argument;
        position: 0;
    }
    select $use;
}
```

El bloque vacío enumera los usos conocidos. Los filtros se aplican conjuntamente;
`kind` acepta un nombre o una lista de strings. Se admiten:

| Propiedad | Significado |
| --- | --- |
| `kind` | `argument`, `return`, `assignment`, `condition` u `operand` |
| `position` | Posición desde cero del argumento u operando |
| `owner` | Callable propietario, comparado con un rol ya seleccionado |
| `consumer` | Call u Operation consumidora, comparada con un rol ya seleccionado |
| `path` | Ruta fuente; admite string o expresión regular |
| `line` | Línea fuente desde uno |

`Usage` es el tipo de una captura de uso y puede exportarse desde patrones.
La API pública serializa `select $use` como un objeto con `id`, `kind`,
`consumer`, `owner`, `position`, `path` y `line`. La evidencia conserva el valor
capturado y la procedencia que justificó la coincidencia. El ejecutor relacional
interno mantiene IDs estables; no modifica el grafo compartido para agregar usos.
Los atributos también están disponibles en restricciones `where`.

`usages` se escribe fuera de BODY, después de que su Value haya sido capturado
o recibido como entrada de un patrón. No es una instrucción del programa fuente
ni una acción que el buscador ejecuta en ese programa.

## Identidad, posiciones y transformaciones

En `consume(x, x)` hay dos usos: posición 0 y posición 1. Comparten valor, pero
no identidad de uso. Una copia `alias = x` conserva el valor si el flujo lo
acredita; después de `x = other()`, los usos nuevos de `x` dejan de corresponder
al resultado original, mientras que un alias anterior puede conservarlo.

Un argumento expandido (`*items`/`...items`) no es un argumento escalar cuyo valor
sea el paquete completo. La expansión y las posiciones posteriores a un paquete
de tamaño desconocido conservan incertidumbre; no se presentan como posiciones
escalares acreditadas.

En `y = x * 2`, la multiplicación usa `x` como operando. El resultado `y` es
otro valor: `consume(y)` no se devuelve como uso directo del valor de `x`.
No se sigue `FLOWS_TO` histórico ni se propaga identidad mediante dependencias
de valores derivados.

La clasificación identifica al consumidor directo. En `if consume(x)`, `x`
es argumento de `consume`; no es por sí mismo el valor booleano de la rama.
En `if x * 2`, `x` es un operando. En `if load()`, el resultado de `load`
sí se usa directamente como condición. Se excluyen las operaciones marcadas
inalcanzables y los brazos descartados por condiciones booleanas constantes
reconocidas; no se demuestra factibilidad general de caminos.

## Inventario abierto e incertidumbre

Esta versión encuentra consumidores acreditados por el grafo; **no certifica
que el inventario sea exhaustivo**. La procedencia de alias soportada es local
al callable. No se afirma seguir todos los usos a través de heap, closures,
efectos desconocidos, invocaciones dinámicas o llamadas interprocedurales.

El operador conserva un candidato incierto `usage_inventory_open`, además de
las coincidencias conocidas. En modo estricto, ese candidato aparece como
incertidumbre, no como una fila de uso confirmado. Un origen `may` tampoco se
presenta como `must`; los hechos cuyo consumidor falta no crean usos ciertos.

Por ello, cero filas no demuestra que el valor no se utilice; contar las filas
conocidas tampoco prueba que todos los usos cumplan una propiedad. No se ha
implementado un `every usage` basado en un inventario cerrado. `complete` indica
que la ejecución terminó, mientras que `unknown`/`unknown_candidates` conserva
estas limitaciones semánticas.

## Validación

`tests/kql2/test_usages.py` cubre capturas inline, alias, reemplazo de bindings,
posiciones repetidas, valores derivados, consumidores precisos, ramas muertas,
orígenes posibles, hechos incompletos, composición de patrones, caché persistida,
modo de referencia y ausencia de mutaciones del grafo. Hay casos inline en Python,
JavaScript, TypeScript, Java, C#, C++, Go y Rust. Los tests de control, booleanos y
orígenes por iteración validan separadamente el caso callback con `break`.
