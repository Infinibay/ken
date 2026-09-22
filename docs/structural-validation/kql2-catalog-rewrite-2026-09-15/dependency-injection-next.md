# Próxima migración: Dependency Injection y supplied_policy

Análisis durante la suite global; **ningún TOML, motor ni test se modificó**.
Se evaluó una consulta candidata en memoria, sin alterar el catálogo.

## Object assignment: no falta una primitiva

Esta variante observa una entrada externa, su almacenamiento y el uso desde otro
método. Admite configuración condicional como candidato, y no afirma que inyectar
suceda antes de consumir en runtime. BODY debe seguir siendo subsecuencia normal.

```kql2
pattern detect(out TypeDecl $unit, out Field $dependency,
               out Callable $inject, out Callable $operation) {
  type $unit {
    field $dependency {}
    method $inject {
      writes: exactly($dependency, 1);
      parameters { param $supplied { reassigned: false; } }
      body { $dependency = $supplied; }
    }
    method $operation {
      call $invocation {}
      body { call $invocation { receiver: $dependency; }; }
    }
  }
  where $inject != $operation;
}
```

El selector Call liga una ocurrencia, no exige resolver una declaración de destino
que puede no existir en código dinámico/importado. El BODY exige que esa ocurrencia
use el campo seleccionado. No se sustituye la invocación por un predicado oculto.
La prueba en memoria encuentra exactamente un candidato, sin unknown, para cada
fixture de `test_modern_patterns.SOURCES`: Python, JavaScript, TypeScript, Java y
C#. Esto aún no es replay de negativos ni una migración publicada.

Negativos: entrada sustituida; dos escrituras explícitas del campo en inject;
consumir otro campo; configurar y consumir en el mismo método; construir
localmente en lugar de recibir entrada. Los positivos incluyen constructor con
asignación explícita, nombres distintos y rama condicional de inyección.

## Retained object y callable input: comparten supplied_policy

Una vez migrada la retención, las diferencias de consumo ya son expresables:

```kql2
use ken.catalog.strategy.supplied_policy.detect(
  unit: $unit, configure: $inject, policy: $dependency);
type $unit {
  method $operation {
    call $invocation {}
    body { call $invocation { receiver: $dependency; }; }
  }
}
where $inject != $operation;
```

Para callable-input el BODY es `call $dependency {};`: invocar el valor callable
retenido, sin exigir nombre, argumentos ni retorno. Esto conserva continuaciones
sin argumentos, llamadas condicionales y consumidores async. No exigir reenvío de
resultado a todas las modalidades DI: es un refinamiento distinto.

## Mínimo faltante en supplied_policy

### 1. Restricción hasta la salida de un callable

El último input válido puede venir después de escrituras previas. Por ello
`writes: exactly($policy, 1)` **no conserva** esta variante. Ejemplo positivo:

```python
def configure(self, supplied):
    self.policy = None
    self.policy = supplied
```

Propuesta de autoría pendiente (no se declara gramática actual):

```kql2
method $configure {
  parameters { param $supplied { reassigned: false; } }
  body linear {
    $policy = $supplied;
    restriction until exit {
      forbid assign(binding($policy));
    }
  }
}
```

`assign(binding(...))` prohíbe escrituras explícitas del binding fuente; no promete
pureza de setters/descriptores ni estabilidad del heap. `exit` debe incluir salida
normal implícita y retorno explícito; escrituras tras un return inalcanzable no
invalidan el contrato. `body linear` conserva el límite actual frente a branches
y loops de configuración; una futura versión all-path sería más expresiva.

No basta reutilizar `gap` actual: exige dos anchors y rechaza campos como bindings
no locales por sus garantías de alias; además no tiene endpoint de salida del
callable. Tampoco basta `reassigned:false` del parámetro: protege la entrada, no
la última escritura del campo. Un valor que reemplaza el campo después debe
invalidar ese input; otra entrada válida escrita al final debe convertirse en el
rol `$supplied` expuesto.

### 2. Inicializadores reales de constructor

C++ `Context(Policy* p): policy{p} {}` y TS `constructor(public policy: Policy){}`
son positivos existentes sin ASSIGN explícito en BODY. Se necesita normalización
a asignación de inicialización en el AST común o un bloque fuente de inicializador
que participe en el mismo algoritmo de retención:

```kql2
constructor $configure {
  parameters { param $supplied { reassigned: false; } }
  initializer { $policy = $supplied; }
  body {
    restriction until exit { forbid assign(binding($policy)); }
  }
}
```

La propuesta debe también cubrir el constructor explícito corriente usando BODY.
No basta exponer `CONSTRUCTOR_FIELD_INPUT` con otro nombre: hay que mostrar la
inicialización y la restricción posterior. Contraejemplos: inicializar otro campo,
escribir null en el body, modificar el input según el contrato actual o no
consumir el campo. La normalización debe conservar procedencia (implícita vs
explícita), orden antes del cuerpo, y cantidad de escrituras.

## Tests existentes que deben conservarse

- `test_modern_patterns.py`: object DI en cinco lenguajes, constructor, renombres,
  wrong receiver/input, no consumo y colección modern.
- `test_modern_catalog_precision.py`: object injection conserva su witness;
  sobrescritura y rebinding no pueden recuperarse por historia.
- `test_callable_dependency_injection.py`: siete lenguajes (Python, JS, TS, Go,
  C#, C++, Rust); escritura previa válida, overwrite, input-before/input-after,
  retorno antes, escritura muerta, replacement, wrong-field, no-call, no-input,
  cero argumentos, paréntesis, async y consumidor condicional; descriptor Python,
  variante de interfaz funcional Java, composición por roles y dos métodos.
- `test_strategy_binding_inputs.py`: último input objeto/callable; source-final
  replacement exportado como rol; branches/loops unsupported; campos con
  descriptores; varios posibles targets; inicializadores C++ y TS y negativos.
- `test_algorithm_strategy.py`: contrato algorítmico, ruido y contraejemplos de
  selección/uso; depende de supplied_policy y debe repetirse.
- `test_catalog_ir_contracts.py`: operaciones fuertes y catálogo compartido.
- `test_modern_catalog_review.py`: matrix conceptual de patrones modernos.
- Matriz de `test_catalog_adversarial_matrix.py` + seeds para las tres variantes
  y `strategy.supplied_policy`; repetir canonical/noise/negativos completos.

No se deben invertir los positivos `prior-write`, `return-after/dead-write` ni
los inicializadores de constructor para facilitar una migración incompleta.

## Implementación de este corte

La familia Dependency Injection ya usa selectores/BODY en el TOML principal y
sus tres variantes. `strategy.supplied_policy` se reescribió a partir de dos
algoritmos: asignación de un parámetro estable seguida por ausencia de nuevas
asignaciones hasta la salida, o transferencia en la fase de inicialización del
constructor seguida por esa misma restricción. Ninguno usa `edge` ni un
predicado que oculte el patrón completo. Se conservaron los roles públicos de
las consultas dependientes.

Primitivas nuevas: `gap until exit { forbid assign(binding($field)); }` e
`initializer { $field = $parameter; }` al inicio del BODY. El contrato preciso,
los límites de alias/heap y el alcance de región están en
[`saved-body-execution.md`](../../design/kql2/saved-body-execution.md).
El initializer de esta fase no equivale al matcher de argumentos `initializer
$state { transfer: ...; }` dentro de `construct`: uno describe declaración de
un constructor y el otro una entrada a una construcción.

Verificación de este corte:

- 70 tests nuevos: final write positivo/negativo en Python, Java, TypeScript,
  C# y C++; inicializadores TypeScript/C++; logging, retorno temprano,
  escritura descartada por flujo, reasignación del parámetro, reflexión,
  publicación directa/alias/contenedor del receiver y sintaxis inválida.
- 149 tests existentes de entradas Strategy pasan, excluyendo su prueba de
  rendimiento pendiente de optimización del join.
- 153 celdas de la matriz adversarial Dependency Injection/Strategy pasan.
- 120 tests de regresión BODY/gaps/calls/conditions y storage Singleton pasan.
- El conjunto de catálogo/Strategy/callable DI/revisión moderna y los primeros
  52 tests nuevos pasó 743 pruebas; los 18 tests nuevos posteriores también
  pasan en el archivo completo de 70.

Rendimiento pendiente de cierre: la prueba de 120 contextos con 8 campos y 8
parámetros excede su presupuesto de 10.000 estados tras la migración. El plan
source inicialmente liga todos esos participantes antes de evaluar BODY. La
corrección adecuada es adelantar una restricción interna de participantes de
la asignación antes del producto cartesiano, conservando la comprobación
completa del BODY y su restricción terminal. No se alteró el límite para
esconder este problema. El coordinador está revisando esa optimización.
