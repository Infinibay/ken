# Singleton: del algoritmo en palabras al IR

Singleton necesita un **ámbito de unicidad**. Una instancia por clase/cargador,
módulo, worker, proceso, tenant o contenedor de dependencias no significa una
instancia global en todas las ejecuciones. El
[catálogo](../../../../src/ken/structural/patterns/singleton.toml) detecta formas
estructurales lazy/eager y publica las operaciones `singleton.lazy_instance` y
`singleton.shared_instance`; no demuestra unicidad global ni seguridad concurrente.

## Algoritmo en palabras

Para acceso lazy secuencial:

1. Identificar el slot compartido y el ámbito que lo posee.
2. Leer si ya contiene una instancia publicada.
3. Si falta, crear la instancia requerida, completar su inicialización y guardarla
   en ese mismo slot.
4. Tanto si existía como si acaba de crearse, devolver la instancia retenida.
5. Si se promete identidad estable durante la vida del ámbito, impedir o modelar
   reinicios, sustituciones y otras rutas de construcción relevantes.

Para eager, la creación y publicación ocurren al inicializar el ámbito; el acceso
lee el slot ya inicializado. No exigir un `if` artificial a esta variante.

Para acceso concurrente, la operación debe coordinar a los solicitantes según un
protocolo demostrado: elegir/publicar una instancia y exponerla inicializada, con
visibilidad de memoria suficiente. La exclusión mutua no se infiere del nombre
`lock`, `once`, `safe` o `getInstance`. Deben resolverse el objeto sincronizador,
su API efectiva y las operaciones protegidas.

## Identidades y obligaciones

| Elemento | Requisito |
| --- | --- |
| Ámbito | Está declarado o acotado por evidencia; no inventar ámbito de proceso |
| Slot | El guard, la publicación y las devoluciones se refieren al mismo slot |
| Instancia | La instancia creada alimenta la publicación y tiene el contrato requerido |
| Estado del slot | El brazo de creación corresponde a ausencia, no a presencia |
| Retorno | Cada salida admitida devuelve el objeto retenido, no otra creación |
| Inicialización | Las operaciones requeridas ocurren antes de publicación cuando se exige |
| Historia | Las escrituras posteriores son compatibles con el ciclo de vida prometido |
| Sincronización | Misma identidad del lock/once; protección y orden de memoria adecuados |

Un contador independiente no altera la identidad del slot. Una llamada que recibe
el slot, su propietario o una referencia compartida puede alterarla: necesita un
resumen de efectos. Conservar el nombre de la variable no prueba conservar el
objeto ni su contenido.

## IR objetivo

Notación de diseño, no gramática textual ejecutable ni KenQL nueva:

```text
function get(%scope) {
  %slot = shared.addr %scope [field = instance]
  %current = memory.load %slot
  %result = choose is_absent(%current) {
    absent {
      %created = construct @Service()
      memory.store %slot, %created
      output %created
    }
    present { output %current }
  }
  return %result
}
```

`shared.addr` y la política de ausencia son requisitos explícitos de diseño.
El núcleo dispone de regiones, memoria, valores y control; esto no implica que
el matcher reconozca ya cualquier secuencia equivalente. En particular, un
retorno por variable local y una lectura del slot requieren correlacionar el
estado alcanzado por cada rama.

Un contrato de preservación útil permite trabajo independiente entre guard,
creación, publicación y retorno. El intervalo protegido cubre identidad del slot
y operaciones que puedan invalidar la decisión de ausencia. Saltar un número
arbitrario de aristas CFG no basta: podría atravesar `slot = null`, otra asignación
o una llamada que publique el propietario.

Modelo propuesto de once, separado de la variante secuencial:

```text
%value = once.get_or_initialize %cell {
  %created = construct @Service()
  initialize %created
  output %created
} [scope = declared, publication = modeled, failure_policy = modeled]
return %value
```

`once.get_or_initialize` todavía requiere un modelo de API. La política debe
especificar qué pasa si falla el inicializador, si puede reintentarse, si es
reentrante y si hay cancelación. No reducir todas las APIs once a un mismo hecho
“llama una vez”: ejecutar un callback, retener su resultado y publicar memoria son
propiedades diferentes.

## Variantes por lenguaje y ámbito

| Variante | Ejemplos a modelar | Precaución de interpretación |
| --- | --- | --- |
| Campo de clase lazy | Python classmethod, Java/TS/C# static accessor | La firma no prueba sincronización ni constructor privado |
| Campo de clase eager | Java/C#/TS | Depende del ciclo de inicialización del ámbito; no inferir inmutabilidad total |
| Export de módulo | Python/JS/TS | Identidad depende del módulo/cargador y del entorno de ejecución |
| Local estático | C++ | Distinguir variable local persistente de local nuevo en cada invocación |
| Once/celda | Go `sync.Once`, Rust `OnceLock`/`LazyLock`, C++ `call_once` | Resolver API, identidad de celda y transferencia del resultado |
| Holder/enum | Java | Otro mecanismo de inicialización; no exigir null guard visible |
| Contenedor DI | Varios lenguajes | Lifetime singleton puede estar limitado al contenedor/tenant |
| Memoización por clave | Varios lenguajes | Varias instancias según clave; no colapsarlo a unicidad sin ámbito/key |

Los nombres de API de esta tabla son candidatos para futuros modelos, no pruebas
implementadas de sus garantías. El catálogo marca `once-primitive` como `design`;
`module-shared` pasó a `ready` en IR 1.57 para export de módulo (Python/JS/TS/Go/Rust)
y local estático (C++), con la precaución "local persistente vs. local nuevo en cada
invocación" resuelta marcando `static` en la declaración de C++. Holder/enum,
contenedor DI y memoización por clave siguen sin modelo. Los tests no validan
protocolos concurrentes.

## Uso de named queries

La consulta usada por los nuevos tests compone detección con uso real:

```kenql
query observed_lazy_use {
  match "singleton.lazy_instance"(unit:$unit, storage:$storage,
                                 accessor:$accessor, creation:$creation);
  require $call TARGET $accessor;
  emit $unit, $storage, $accessor, $creation, $call;
}
```

Esto responde “qué llamada usa ese accessor” y conserva el owner del slot. No
prueba cuántos objetos existieron ni que todos los clientes usen el accessor.
Una llamada a `Other.get()` no debe cruzarse con evidencia de `Shared.get()`,
aunque ambos tengan un campo `value` y el mismo nombre de método.

## Evidencia nueva, sin repetir las matrices previas

[`test_algorithm_singleton.py`](../../../../tests/structural/test_algorithm_singleton.py)
complementa las matrices previas de polaridad de null, escrituras, constructores,
eager y retornos. Analiza Python, Java y TypeScript:

- Dos usos positivos compuestos, Java y TypeScript, con cálculo/logging antes y
  después de la llamada en el cliente.
- Tres negativos de uso: el cliente llama al owner equivocado. Los slots y
  accessors tienen nombres iguales, pero no se mezclan sus pruebas.
- Tres positivos de firma secuencial sin sincronización. Se etiquetan como
  candidatos, nunca como prueba de seguridad concurrente.
- Un positivo deseado todavía no detectado: uso de classmethod Python a través
  de la clase. La firma lazy existe, pero falta `TARGET` para componer ese uso.
- Seis positivos deseados no detectados: aritmética local pura antes del guard o
  antes del retorno, en los tres lenguajes. No hay llamadas en ese ruido.

**Resultado: 8 passed, 7 xfailed.** Los siete xfails estrictos son falsos negativos
reproducidos de esas búsquedas; no cuentan como detección exitosa. No se inventa
un test de thread safety sobre una query que sólo promete firma estructural.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_singleton.py
```

## Causas y mejoras necesarias

La operación lazy exige `CFG_ENTRY` igual al guard y enlaces directos al retorno.
Por eso incluso una multiplicación de constantes almacenada en un local nuevo
rompe la búsqueda. El modo eager también tiene un contrato de accessor directo,
con gaps de ruido ya documentados en sus tests anteriores.

No se reemplazaron estas condiciones por un `path CFG_NEXT` sin restricciones:
relajaría el control y podría aceptar reasignaciones que anulen la inicialización.
Hace falta una secuencia con preservación de estado y efectos entre eventos,
aceptando instrucciones conocidas independientes y manteniendo `unknown` para el
resto. Así la query expresa el algoritmo sin depender de adyacencia sintáctica.

La composición Python tiene otra causa: la resolución `direct-class-static` en
`semantic.py` cubre Java, C#, JavaScript y TypeScript; no resuelve ese classmethod.
Su solución requiere modelar el binding de clase Python, no comparar sólo nombres.

Para llegar a garantías fuertes faltan además ámbito/lifetime, orden de publicación,
modelos de sincronización y escape, rutas externas de creación y reinicio. Un
análisis parcial debe declarar cuál de esas propiedades observó. El ejercicio no
cambia motor/TOML ni atribuye al núcleo actual garantías de concurrencia nuevas.
