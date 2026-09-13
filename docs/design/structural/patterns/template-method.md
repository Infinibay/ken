# Template Method

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/template-method.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** algoritmo estable, pasos reemplazables, implementación de paso y contexto
compartido. **Grafo:** algoritmo establece secuencia de llamadas a slots; un slot
es reemplazable y usado por ese algoritmo. La secuencia requiere CFG, no solamente
que existan dos métodos en una clase.

| Lenguaje | Fragmento del algoritmo |
|---|---|
| P | `def run(self): self.open(); self.step(); self.close()` con `step` redefinido |
| JS | `run() { this.open(); this.step(); this.close(); }` con subclass que redefine `step` |
| TS | `run(): void { this.open(); this.step(); this.close(); }` con hook `protected abstract step(): void` |
| J | `final void run(){ open(); step(); close(); }` con `protected abstract void step();` |
| CS | `void Run() { Open(); Step(); Close(); }` con `protected abstract void Step();` |
| CPP | `void run() { open(); step(); close(); }` con `virtual void step() = 0;` |
| G | `func Run(h Hooks) { h.Open(); h.Step(); h.Close() }` — variante de esqueleto por composición |
| R | `trait Job { fn step(&self); fn run(&self) { self.open(); self.step(); self.close(); } fn open(&self); fn close(&self); }` |

**Portabilidad:** la fila Go no es herencia ni override; etiquetar variante funcional.
**Negativo:** función que llama tres helpers fijos sin puntos de extensión.
**Límite:** los ejemplos no aseguran `close()` tras una excepción; esa obligación
es otra regla, dependiente de recursos y CFG excepcional.

