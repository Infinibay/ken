# Campos C++: declaradores y tipos del slot — implementado en IR 1.36.0

La revisión de Bridge mostró dos identidades: el campo implementor existe porque
se declara previamente, pero TYPE_NAME se asigna al nodo de expresión *implementor.
La llamada usa el campo y pierde el contrato. Lo mismo puede afectar Adapter,
Strategy, State y cualquier regla que combine receptor con tipo nominal.

Se normalizan los declaradores de campos de clases/structs C++ hacia un solo slot,
con independencia de que aparezcan antes o después del método. Se conserva el
tipo abstracto escrito quitando únicamente el identificador de la variable:
punteros, referencias, cualificadores y arrays no se borran del native_type.
Cada declarador de una declaración múltiple tiene su propio tipo e inicializador.
Los métodos no se convierten en campos. Los punteros a función se conservan
como campos de tipo opaco; su nombre no es el del parámetro del callback.
IR 1.36.0 no incorporaba las declaraciones de métodos sin cuerpo como callables.
Por ejemplo, `virtual void request() = 0;` conserva su sintaxis, pero no publica
el slot HAS_METHOD que permitiría enlazar OVERRIDES desde una implementación
derivada. IR 1.37.0 incorpora esos slots bajo el [contrato de métodos C++](cpp-method-contracts.md);
las firmas no soportadas siguen sin enlaces de override, aunque no haya errores
de parsing.

Para tipos nominales simples, sin arrays ni declaradores de función y con a lo sumo
una indirección, TYPE_HEAD conserva el tipo base que puede actuar como contrato
nominal del receptor. No se adivina el basename de un tipo cualificado ni se
asimila Driver** a un receptor Driver*. Las formas más complejas siguen
representadas como sintaxis y tipos estructurados/opacos, sin resolver contratos
que no estén demostrados por el modelo.

Los descriptores de tipo distinguen cualificación const/volatile y referencias
lvalue/rvalue en su forma escrita. La cualificación no implica inmutabilidad del
objeto apuntado ni seguridad concurrente. TYPE es evidencia nominal en el modelo,
no prueba de inicialización, validez del puntero, ownership o valor runtime.

Los inicializadores de campo escritos con = se correlacionan por declarador;
las listas de inicialización de constructores quedan fuera de este cambio y no
se infiere asignación de parámetros a campos por coincidencia de nombres.
Se preservan el AST y sus operaciones incluso cuando un declarador no se puede
normalizar. Un estado explícito por declaración separa los casos soportados de
los opacos/no reconocidos; la ausencia no significa que no exista un campo.

Los tests cubren antes/después del uso, declaraciones múltiples, nombres
renombrados, punteros/referencias y calificadores, arrays/callbacks sin contratos
falsos, inicializadores asociados al campo correcto y regresiones en otros
lenguajes. El corpus C++ se comparó sobre las mismas fuentes y se revisaron
los roles de todos los matches nuevos. La documentación publica por separado
las mejoras de normalización, los TP del patrón y las ambigüedades de intención.

## Revisión después del primer escaneo

La normalización recupera Facade en el corpus C++, pero también hace visibles
campos usados por Decorator. La variante antigua de Bridge los confunde porque
sólo comprueba que la abstracción y el contrato sean IDs distintos. Se aplica
la separación por NOMINAL_ROOT a la ruta C++ de runtime-composition y se probó el pase
de raíces sobre las bases nominales explícitas C++. Esto evita convertir una
jerarquía Decorator en dos familias independientes. Se compararon los matches
anteriores para documentar cualquier pérdida de cobertura o evidencia no resuelta.

TYPE_HEAD_STATUS distingue los declaradores con receptor nominal simple de los
complejos: el linker no debe eliminar todos los asteriscos y resolver Driver**
como Driver sólo porque existe un nombre local. El tipo escrito y sus capas
permanecen consultables incluso cuando no se publica TYPE hacia ese contrato.


Al aplicar esa condición a todos los lenguajes se perdió ExtendedAbstraction del
Bridge Python de Pandovski, cuyo abc.ABC no está resuelto. La corrección final se
limita a las coincidencias C++ introducidas por esta normalización; no cambia la
firma runtime anterior de los demás lenguajes. Sus FP conocidos de Decorator
Java/C# siguen pendientes. No se presenta una raíz desconocida como independencia.


## Estados y tipos consultables

- CPP_FIELD_DECL_STATUS pertenece a la operación de declaración: supported,
  unsupported o not-storage, con la cantidad de campos normalizados. No expresa
  completitud de tipos, inicialización ni validez del programa.
- TYPE_HEAD_STATUS pertenece al campo y describe la disponibilidad de un head
  nominal simple por sintaxis. El linker respeta unsupported y no quita múltiples
  indirecciones para adivinar un contrato. Encontrar TYPE_HEAD no prueba que ese
  nombre se haya resuelto a una declaración.
- TYPE_QUALIFIER distingue const/volatile por capa de TYPE_REF. reference conserva
  la referencia lvalue y rvalue_reference representa &&. Los declaradores con
  paréntesis de precedencia (puntero a array o función) quedan opacos como conjunto,
  sin reinterpretarlos como arrays de elementos escalares.

Ejemplo de fragmento analizable:

```cpp
class Backend {};
class Fields {
  const Backend *readonly_target;
  Backend * const fixed_pointer = nullptr;
  Backend &reference;
  Backend &&temporary_reference;
  Backend **indirect;
  Backend values[3];
  Backend (*matrix)[3];
  void (*callback)(int);
  Backend *first = nullptr, second;
};
```

| Campo | Evidencia del tipo | Contrato nominal por anotación |
|---|---|---|
| readonly_target | pointer → qualified(const) → Backend | Backend |
| fixed_pointer | qualified(const) → pointer → Backend | Backend |
| reference / temporary_reference | reference / rvalue_reference → Backend | Backend |
| indirect | pointer → pointer → Backend | No se infiere un receptor Backend. |
| values | array de tres Backend | No se infiere un receptor escalar Backend. |
| matrix / callback | Tipo opaco con ortografía conservada | No se infiere un contrato. |

La inicialización de first corresponde a su propio declarador; no se atribuye
nullptr a second. El fragmento no instancia Fields ni demuestra que una referencia
o un puntero sean utilizables. [Auditoría, regresiones y problemas pendientes](../../structural-validation/multilanguage/cpp-field-declarators.md).
