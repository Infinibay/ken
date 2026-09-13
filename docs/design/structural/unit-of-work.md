# Unit of Work: cambios diferidos por categoría

Implementado en IR 1.24.0. La primera variante se basa en el ejemplo Unit of Work de iluwatar: un método
registra entidades en lotes asociados a una clave de operación; un coordinador
llama helpers que recorren esos lotes y envían cada entidad a un mismo store.
Se exigen al menos dos acciones distintas de persistencia. Los nombres de clases,
registradores, coordinador y helpers son libres.

La firma conserva estas correlaciones:

1. La entidad agregada al lote y la clave del lote son parámetros distintos del
   mismo registrador.
2. El lote procede de `get`/`GetValueOrDefault` sobre el campo de cambios y se
   vuelve a guardar en ese campo bajo la misma clave, por `put`/`set` o índice.
3. Un coordinador resuelve llamadas a helpers del mismo objeto. Cada helper
   recorre un lote obtenido del campo de cambios y pasa el binding de esa
   iteración a una operación del campo store.
4. El mismo coordinador y store reúnen al menos dos nombres de operación entre
   insert, update, modify, delete y save (y convenciones PascalCase).

Esto es una firma estructural de Unit of Work con cambios diferidos. Las formas
de APIs son evidencia explícita, no una resolución de drivers de base de datos.
Un batch processor con esa misma forma puede compartir la firma. No se prueba
atomicidad, transacción, rollback, orden, estabilidad de aliases, ejecución de
helpers ni que las claves registradas se encuentren entre las consumidas.
`ASSIGNED_FROM` aporta procedencia posible en el registrador, no reaching
definitions completos. Para consumir el lote se exige `ITERATION_ORIGIN`, con
una escritura local simple anterior al uso y sin aliases escapados/sobrescritos.
`ITERATION_PASSES_VALUE` conserva la posición del elemento en la llamada de
persistencia. `INSERTED_INPUT` excluye escrituras explícitas del parámetro antes
de considerarlo la entrada insertada. Estos modelos no certifican efectos ocultos.

La operación pública `keyed_flush` se guarda junto con la query en el mismo
TOML. Permite consultar los helpers, acciones y entidades procesadas sin copiar
la consulta. Se extendió el IR para expresar procedencia positiva: contar cero
escrituras en un grafo incompleto no prueba su ausencia, y KenQL mantiene esa
restricción. Una variante
transaccional, colecciones de cambios separadas, listeners ORM, async y cambios
en el heap necesitan modelos y pruebas adicionales.

```kenql
query deferred_actions {
 match "persistence.unit-of-work.keyed_flush"(
  unit:$unit, worker:$worker, item:$entity, action:$action
 );
 emit $unit,$worker,$entity,$action;
}
```

La operación puede exponerse aunque el coordinador tenga una sola acción; la
query raíz del patrón exige al menos dos acciones distintas. Son preguntas
diferentes que usan el mismo grafo y el mismo mecanismo de composición.
