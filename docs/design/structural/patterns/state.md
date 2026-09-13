# State

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/state.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** contexto, slot de estado, comportamientos alternativos y transición.
**Grafo:** dispatch depende del estado actual; una acción/evento cambia ese estado,
afectando futuras llamadas. La transición debe modificar el mismo slot que gobierna
la selección. Enum + match también es variante, sin obligar a objetos State.

| Lenguaje | Fragmento de transición y dispatch |
|---|---|
| P | `def request(self): self.state.handle(self)` / `ctx.state = Ready()` |
| JS | `request() { this.state.handle(this); }` con transición `ctx.state = ready` |
| TS | `state: State; request() { this.state.handle(this); }` con escritura de estado |
| J | `void request(){ state.handle(this); } void become(State s){ state=s; }` |
| CS | `void Request() => state.Handle(this); void Become(IState s) => state=s;` |
| CPP | `void request() { state_->handle(*this); }` con reemplazo del `state_` apropiado |
| G | `func (c *Context) Request() { c.State.Handle(c) }` con `c.State=Ready{}` |
| R | `self.state = match self.state { State::Idle => State::Ready, State::Ready => State::Done, State::Done => State::Done };` |

**Portabilidad:** evitar requerir préstamo simultáneo incompatible en ejemplos Rust;
el enum ilustra otra implementación. **Negativo:** inyección de algoritmo elegido
por configuración sin transición de comportamiento observada. **Límite:** cambiar
una Strategy en runtime puede tener la misma forma. Reportar ambigüedad.



## Implementación IR 1.29.0

La variante `context-transition` añade acciones de estados que instalan un sucesor
mediante el setter del contexto, con parámetros-propiedad TypeScript y contratos
nominales. Hay tests positivos, renombrados y negativos cercanos en cinco lenguajes.
La [especificación implementada](../state-context-transitions.md) describe las
relaciones y los límites de identidad, orden e intención. `state-enum` sigue pendiente.
