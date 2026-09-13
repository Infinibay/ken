# Operaciones públicas de patrones

Estado: `[[operations]]` y `iterator.iterate_over` están implementados y probados
en ocho lenguajes. La sintaxis `%… do … %end` y las operaciones map/filter siguen
propuestas. La [guía IR](../../structural-ir.md) contiene un ejemplo ejecutable.

Un patrón puede publicar consultas que describen usos, además de la consulta que
reconoce su implementación. Una operación devuelve roles correlacionados con
evidencia; no ejecuta código fuente ni expande texto arbitrario.

Interfaz disponible:

```kenql
match "iterator.iterate_over"(
  source: $iterator,
  item: $instance,
  body: $body,
  iteration: $iteration
);
```

Los cuatro roles provienen de una misma coincidencia. Las restricciones siguientes
pueden inspeccionar usos de `$instance` dentro de `$body`. La operación debe
modelar la identidad del elemento: no basta encontrar un identificador homónimo.
Un `for`, un cursor explícito, un generador y una API de streams pueden necesitar
variantes diferentes que implementen esa misma interfaz pública.

Una operación lista contiene su query en el TOML del patrón. `iterate_over` ya
usa este formato. El siguiente bloque ilustra también declaraciones futuras;
map/filter todavía no forman parte del catálogo ejecutable:

```toml
[[operations]]
id = "iterate_over"
status = "ready"
description = "Relaciona fuente, elemento y región consumidora."
query = '''
query iterate_over {
  require $iteration ITERATION_SOURCE $source;
  require $iteration ITERATION_BINDING $item [role: value];
  require $iteration ITERATION_BODY $body;
  emit $source, $item, $body, $iteration;
}
'''

[[operations]]
id = "map"
status = "design"
description = "Relaciona fuente, transformación, elemento y salida."

[[operations]]
id = "filter"
status = "design"
description = "Relaciona fuente, predicado y salida seleccionada."
```

La identidad pública sería `iterator.iterate_over`, `iterator.map` y
`iterator.filter`. `select` puede ser alias explícito de filter únicamente cuando
su modelo de lenguaje/API tiene esa semántica: en otras APIs Select transforma.
No deducir estas operaciones por el nombre map/filter/select solamente.

## Bloques de uso

El ejemplo `%iterate_over(iterator) do |instance| … %end` puede ser azúcar para
el match y la restricción de región. La expansión debe introducir aliases frescos
y anclar las restricciones del bloque al cuerpo o callback correspondiente.
No basta un match seguido de una búsqueda global del mismo nombre de variable.

Invocar la operación no obliga a obtener primero una coincidencia GoF sobre la
implementación del tipo: una colección incorporada puede exponer la operación
sin que su implementación esté en el repositorio. La variante debe aportar la
evidencia de protocolo, sintaxis o modelo de API que la justifica.

## Contratos y validación

- Separar ejecución inmediata, diferida y async; construir un pipeline no prueba
  que se haya consumido. Conservar orden, cancelación y suspensión como propiedades
  conocidas o desconocidas, no defaults silenciosos.
- Map no equivale a cualquier callback: deben correlacionarse entrada,
  transformación y salida. Filter conserva elementos seleccionados por el
  predicado; no se debe sustituirlo por cualquier rama condicional.
- Registrar variantes eager/lazy y de cada protocolo dentro del mismo fichero.
  Las operaciones no se incorporan a la unión del detector GoF del patrón.
- Validar nombres y exports, detectar colisiones, mantener higiene y rechazar
  dependencias recursivas no soportadas con la misma política de queries nombradas.
- Probar loops, comprehensions, callbacks y pipelines en varios lenguajes, con
  negativos por otra colección, otro elemento, predicado no aplicado, callback
  no ejecutado y salida descartada.

La primera operación usa relaciones de foreach y conserva source/item/body/iteration
en la misma coincidencia. La variante actual no reconoce todas las implementaciones
de iteración ni garantiza resolución completa del shadowing en bloques. El azúcar
sintáctico y map/filter necesitan modelos y tests adicionales; no reemplazan el
análisis semántico necesario.
