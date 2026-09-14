# `observer#language-event` (C#) — diagnóstico medido

Estado: **bloqueado**, con la brecha acotada a una capacidad concreta.
Fecha: 2026-09-13. Base: `1df0e9d`.

## Qué pide la ficha

> Identificar event de C#, registro/remoción de handlers e invocación del mismo
> almacenamiento. Modelar accessors personalizados sólo si su semántica es
> conocida. Positivo: dos handlers, baja de uno y emisión con payload
> correlacionado.

Es la única variante del inventario que declara **un solo lenguaje** (`csharp`),
y C# ya está admitido en `structured-locals/3`. Es la candidata natural a cerrar.

## Qué da el IR hoy

Fixture:

```csharp
public class Publisher {
    public event Action<int>? Changed;
    public void Raise(int payload) { Changed?.Invoke(payload); }
}
public class Subscriber {
    public void Attach(Publisher publisher) { publisher.Changed += OnChanged; }
    public void Detach(Publisher publisher) { publisher.Changed -= OnChanged; }
    void OnChanged(int payload) { }
}
```

| Necesidad | Evidencia actual | Veredicto |
|---|---|---|
| Declaración del event | `DECLARES`/`HAS_FIELD CLASS:Publisher -> STORAGE:Changed` con `type='Action<int>'` | existe, **pero sin marca de evento** |
| Sintaxis de la declaración | nodo propio `event_field_declaration` | disponible, sin usar |
| Token de add/remove | `op.attrs['tokens'] == ['+=']` / `['-=']` | **disponible** |
| Target de la asignación | `ASSIGNMENT_TARGET -> MEMBER:Changed` (externo) o `STORAGE:Changed` (interno) | disponible |
| Invocación | `CALLEE_NAME: CALL -> 'Changed?.Invoke'` + `READS: Raise -> STORAGE:Changed` | parcial |
| Resolución miembro→campo | **no existe** | **brecha** |

## Las tres brechas concretas

1. **El `event` no se marca.** `event_field_declaration` se procesa como un campo
   corriente: `STORAGE:Changed` con tipo delegado, indistinguible de un campo
   `Action<int>` normal. Tampoco se distingue `+=` sobre un evento de `+=`
   aritmético, que es justo lo que el plan pide separar.

2. **No hay resolución miembro→campo.** Para `publisher.Changed += OnChanged` el
   IR produce `MEMBER:Changed` con `MEMBER_OF PARAMETER:publisher`, y el parámetro
   **sí** tiene `type='Publisher'`. Falta el paso que une
   `MEMBER:Changed` (receptor de tipo nominal `Publisher`) con
   `STORAGE:Changed` de `CLASS:Publisher`. Sin él no se puede afirmar «el mismo
   almacenamiento» para el registro externo.

3. **La invocación no está ligada al evento.** Dentro de la clase, `Changed`
   resuelve bien (`READS: Raise -> STORAGE:Changed`), pero la llamada solo
   registra `CALLEE_NAME = 'Changed?.Invoke'`; no hay hecho que diga «esta llamada
   emite este evento».

## Por qué no se cerró con una query local

Un contrato limitado a los métodos **dentro** de la clase resolutora
(`Attach`/`Detach`/`Raise` sobre `STORAGE:Changed`) sí es alcanzable hoy: los tres
nombres resuelven directo al almacenamiento. Pero eso deja fuera el registro desde
otra clase, que es el caso que la ficha describe («dos handlers, baja de uno») y
el que distingue Observer de un campo delegado cualquiera.

Publicar la variante con esa versión reducida habría exigido recortar el contrato
sin decirlo, que es lo que el plan prohíbe. Se prefiere registrar la brecha.

## Diseño propuesto para cerrarla

1. **Marcar la declaración** en `frontend.semantics`, rama de declaración de
   campo: si el ancestro es `event_field_declaration`, emitir
   `class DECLARES_EVENT storage` (con `name` y el tipo delegado en `attrs`) y
   `attrs['event'] = True` en el STORAGE. El `HAS_FIELD` existente se conserva
   para no romper a los consumidores actuales.
2. **Resolver miembro→campo por tipo nominal.** En el enlazado, para un
   `MEMBER:Changed` cuyo receptor es un binding con `type` nominal conocido,
   unir con el `STORAGE` del mismo nombre declarado en esa clase. Emitir
   `MEMBER_DECLARATION` (o reutilizar el vocabulario existente si ya hay una
   relación equivalente). Es una capacidad general de P4, no específica de
   eventos: conviene probarla también con un campo corriente.
3. **Add/remove.** Con el target resuelto a un `STORAGE` marcado `event`, emitir
   `ADDS_HANDLER` / `REMOVES_HANDLER` desde el callable según `tokens` (`+=` /
   `-=`). Un accessor personalizado (`add { }` / `remove { }`) debe quedar
   `unknown`, no adivinarse.
4. **Emisión.** Ligar la invocación al evento: `RAISES_EVENT` desde la llamada
   (o el callable) al `STORAGE` del evento, reconociendo `Changed?.Invoke(...)`,
   `Changed(...)` y `Changed.Invoke(...)`.
5. **Query y tests.** Positivo con dos registros y una baja desde otra clase;
   negativos: `+=` sobre un `Action` que **no** es `event`, accessor
   personalizado, evento de otra clase, e invocación de un delegado ajeno.

La correlación payload→parámetro del handler es un refinamiento más fuerte que
requiere contratos callable (P4) y **no** debería exigirse a la raíz de la
variante.

## Archivos a leer antes de retomar

- `src/ken/structural/frontend.py`, rama de declaración de campo en `semantics`
  (donde ya se calcula `static` para `scope == cls`) y `ASSIGNMENTS`.
- `src/ken/structural/semantic.py`, enlazado de `MEMBER_OF` y resolución de
  miembros.
- `src/ken/structural/patterns/observer.toml`, variantes `language-event` y
  `event-bus` (comparten el modelo de bus/registro).

## Nota de alcance

`observer#event-bus` (ocho lenguajes) depende del mismo modelo de registro +
publicación sobre la misma identidad de bus/canal. Cerrar el paso 2 (resolución
miembro→campo) sirve a ambas variantes y probablemente a `mediator` y
`singleton#module-shared`.
