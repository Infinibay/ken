# `adapter#class-adapter` (Python/C++) — cerrada

Estado: **cerrada**. La variante es `ready` en sus dos lenguajes declarados.
Fecha: 2026-09-13. Base: `e46c0b6`.

## Tercera variante que no necesitó capacidad nueva

El IR ya resolvía lo que la ficha pide, incluida la parte que parecía difícil:

| Necesidad | Evidencia ya existente |
|---|---|
| Herencia del contrato objetivo | `SUBTYPE_OF CLASS:Adapter -> CLASS:Target` |
| Herencia de la implementación adaptada | `SUBTYPE_OF CLASS:Adapter -> CLASS:Adaptee` |
| Slot destino y su sobrescritura | `HAS_METHOD` en ambas bases + `OVERRIDES Adapter.request -> Target.request` |
| Método efectivo de la base adaptada | `TARGET CALL:self.specific() -> Adaptee.specific` |

El último es el interesante: la resolución de llamadas **atraviesa las bases**
cuando el método no está en la clase receptora, así que `self.specific()` llega a
`Adaptee.specific` sin que el receptor declare nada. Lo mismo en C++ con
`this->specific()`.

## Contrato publicado

```kenql
query adapter {
 require $unit SUBTYPE_OF $target;
 require $unit SUBTYPE_OF $adaptee;
 different $target $adaptee;
 require $target HAS_METHOD $slot;
 require $unit HAS_METHOD $override;
 require $override OVERRIDES $slot;
 require $override HAS_CALL $call;
 require $call TARGET $delegate;
 require $adaptee HAS_METHOD $delegate;
 emit $unit, $target, $adaptee, $slot, $override, $delegate;
}
```

La obligación que define la variante son las **dos bases distintas**: heredar el
contrato objetivo y heredar la implementación adaptada. Sin `different $target
$adaptee` cualquier sobrescritura trivial cumpliría.

**Lo que no prueba** (declarado en `query_claim`): el MRO completo de Python ni el
orden de bases de C++ más allá de que ambas existan, ni que el slot se invoque en
ejecución.

### Límite medido: adaptación con el mismo nombre de método

La ficha pide «probar adaptación con el mismo nombre de método: la desigualdad de
nombres no define este patrón». La primera mitad se cumple —la query **no compara
nombres**— pero el caso positivo con nombres iguales es hoy un **falso negativo
declarado**:

```cpp
struct Target  { virtual int request() = 0; };
struct Adaptee { int request() { return 1; } };
struct Adapter : Target, Adaptee {
  int request() override { return Adaptee::request(); }   // calificación explícita
};
```

```python
class Adapter(Target, Adaptee):
    def request(self):
        return Adaptee.request(self)          # llamada no ligada sobre la clase
```

Medición: en ambos casos `TARGET` queda vacío y la query no matchea. Las causas son
dos, y son capacidades distintas de la que esta variante necesitaba:

- **C++**: `Adaptee::request()` produce un `qualified_identifier` como callee, que
  el frontend no trata como acceso a miembro.
- **Python**: `Adaptee.request(self)` sí es un acceso a miembro, pero el receptor
  resuelve a una **clase**, y la resolución existente solo admite métodos
  `static` para un receptor con valor de clase (camino `direct-class-static`).

No se apuró el arreglo: tocar ese camino tiene riesgo de regresión sobre el
dispatch estático ya validado, y no hace falta para el contrato positivo de la
variante. Queda como límite escrito, con el contraejemplo mínimo y las dos causas.

## Positivo y negativos

Positivo: **1 match** por lenguaje.

| Negativo | Por qué no hay match |
|---|---|
| Object adapter clásico (adaptee en un campo, una sola base) | falta la segunda base |
| Hereda ambas bases pero **no** llama a la operación adaptada | falta `TARGET` al método del adaptee |
| Una sola base | `different $target $adaptee` no tiene segunda base |

Más un positivo con bases y operaciones renombradas (`Contract`/`Legacy`/`Bridge`,
`invoke`/`legacy_call`).

El primer negativo es el que separa las dos variantes de Adapter: el object
adapter ya era `ready` con `SUBTYPE_OF` a una sola base y delegación por campo.

## Archivos

- `src/ken/structural/patterns/adapter.toml`: variante `ready` con query; raíz con
  unión.
- `tests/structural/test_adapter_class_adapter.py`: 8 tests.

Sin cambios en `src/ken/structural/*.py` y sin subir `IR_VERSION`.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_adapter_class_adapter.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
```

- Matriz nueva + catálogo: **278 passed**.
- Suite estructural completa: recuento en el commit.

## Inventario

**51 ready / 26 design** (antes 50 / 27).

## Balance del método

De las siete variantes cerradas en este trabajo, **tres no necesitaron capacidad
nueva** (`template-method#trait-default`, `abstract-factory#associated-products`,
`adapter#class-adapter`) y cuatro sí. La regla que se desprende: **escribir la
query y correrla antes de asumir que falta análisis**. Las tres tenían
`fixtures_status = "documented-not-validated"` y `missing_capability = "unknown"`,
que es exactamente el estado que oculta una variante ya soportada.

## Siguiente paso

`abstract-factory#structural-families` sigue pendiente y es el único caso donde la
query directa **no** sirve: relacionar dos proveedores por su conjunto de
operaciones hace el producto cartesiano que el plan prohíbe, y la medición dio
`budget:max_states` con 30 tipos. Necesita una capacidad de IR que agrupe
operaciones por firma compartida para que el join sea por identidad. Los otros
candidatos sin esa dificultad: `prototype#language-copy`,
`iterator#callback-iterator`, `singleton#module-shared`.
