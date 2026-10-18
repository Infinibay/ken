# Registro persistente de módulos KQL2

Solicitud autorizada: guardar queries y patterns en la DB de Ken, ejecutar
queries por nombre y resolver automáticamente imports en CLI/MCP. El usuario
confirmó conservar el lenguaje actual: queries ejecutables y patterns con
`import/use`, sin convertir `select` en una relación anidada nueva.

## Uso exterior

```python
ken_query(action="save", source=module_source, description="Convenciones de escritura")
ken_query(action="show", module="project.writers")
ken_find(scope="structure", query_language="kql/2",
         saved_query="project.writers", query_name="find_writers", path="src")
# Una consulta inline puede importar project.writers y usar sus patterns.
```

```sh
ken kql2 writers.kql --root /project --save
ken kql2 --root /project --saved project.writers --query find_writers --path src
ken tools query --action list
```

Guardar el módulo completo mantiene un solo nombre y una sola fuente para sus
queries, patterns y declaraciones auxiliares. `--query` elige una entrada cuando
hay varias; con una sola se conserva la selección actual. Las sesiones preparadas
no cachean respuestas.

## Responsabilidades

- **ModuleRegistry:** persistencia en `.ken/ken.db`, listado/lectura/borrado y
  revisiones para actualizaciones concurrentes. Una actualización exige la
  revisión anterior; guardar de nuevo el mismo contenido es idempotente.
- **ModuleResolver:** obtiene la fuente de una entrada guardada y las bibliotecas
  transitivas de un snapshot coherente. Las bibliotecas explícitas prevalecen;
  los módulos incorporados de Ken conservan su namespace reservado.
- **RegistryReader:** lector de larga vida del propietario de consultas,
  consulta la generación del registro y conserva el snapshot mientras no cambie.
  Una modificación del registro no obliga a reindexar archivos del proyecto.
- **Adaptadores:** CLI y MCP delegan en el mismo registro y la misma ejecución
  preparada. Las consultas inline y las reglas existentes mantienen su contrato.

El registro es durable y separado del almacenamiento estructural sujeto a GC.
Su schema es aditivo para bases nuevas y existentes. Lectura de un registro
inexistente no crea una DB. Mutaciones son transacciones, con SQL parametrizado.

## Resolución y consistencia

Una petición fija la fuente y sus imports transitivos antes de compilar; cambios
posteriores se ven en la siguiente petición. Las revisiones usadas aparecen en
el resultado. Las claves de compilación incluyen las fuentes resueltas, por lo
que un cambio transitivo no reutiliza un plan viejo. No se carga todo el registro
en cada consulta ni se reabre una conexión caliente por petición.

Al guardar se comprueban sintaxis, nombres e imports disponibles. Los ciclos de
imports conservan el recorrido sin inicializadores del lenguaje actual y no
causan búsquedas infinitas. La compilación del backend se verifica al ejecutar o explicar; guardar
un módulo no certifica efectos, cobertura, compatibilidad con todos los backends
ni corrección en todas las rutas. Se rechaza borrar un módulo importado por otro.
La recursión de patterns conserva el rechazo actual del compilador.

Las reglas de `ken_rule` fijan los imports registrados como fuentes explícitas
al crear/actualizar la definición, antes de compilar y validar. Así una revisión
del registro no cambia silenciosamente un contrato validado. Para adoptar otra
versión se actualiza la regla con las bibliotecas deseadas y se valida de nuevo.

El monitor de fuentes distingue inputs directos de directorios vigilados sólo
por ser padres de una configuración ausente. Eventos en esos padres comprueban
los inputs declarados antes de invalidar: crear `ken.db` o sus WAL/SHM no equivale
a editar código. Crear `structural.json` sigue invalidando la preparación.

## Entrega incremental y validación

1. DB y CRUD: persistencia entre procesos, DB anterior, idempotencia, conflictos,
   validación sin escrituras parciales y eliminación segura.
2. Resolución: imports transitivos, prioridad explícita, ciclos, actualización y
   snapshot consistente; una biblioteca externa no se ejecuta como código Python.
3. Engine: sesión pública, servicio preparado y compatibilidad/exploration;
   invalidación de planes y recursos correctamente cerrados.
4. CLI/MCP: guardar/listar/mostrar/borrar, ejecutar por módulo/entrada e imports
   inline; compatibilidad de argumentos y errores claros.
5. Skills/referencias: programas completos sobre fixtures mixtos, instalación
   propia y evaluación independiente con ejemplos reales.
6. Suite focal, mypy, suite completa con fuentes congeladas y medición sin carga
   concurrente del corpus de 500 archivos. Se mantiene el criterio aceptado por
   el usuario: gran mayoría dentro de 10 ms, con excedencias visibles.
