# Observer

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/observer.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** subject, registro de suscriptores, suscripción/desuscripción, evento y
callback. **Grafo:** alta inserta callback en colección; notificación recorre esa
misma colección y entrega evento; bajas opcionales según variante. Una colección
de hijos a la que se llama recursivamente no satisface por sí sola esta firma.

| Lenguaje | Fragmento de alta y notificación |
|---|---|
| P | `def on(self, f): self.listeners.append(f)` / `for f in self.listeners: f(event)` |
| JS | `on(f) { listeners.add(f); } emit(e) { for (const f of listeners) f(e); }` |
| TS | `on(f: (e: Event) => void) { this.listeners.add(f); }` con difusión de `Event` |
| J | `void add(Consumer<Event> f){ listeners.add(f); } void emit(Event e){ listeners.forEach(f -> f.accept(e)); }` |
| CS | `public event Action<Event>? Changed;` con `Changed?.Invoke(e);` |
| CPP | `listeners.push_back(callback);` / `for (auto& f : listeners) f(event);` |
| G | `listeners = append(listeners, callback)` / `for _,f:=range listeners { f(event) }` |
| R | `listeners.push(Box::new(callback));` / `for f in &listeners { f(&event); }` |

**Portabilidad:** C# events necesitan modelo de add/remove/invoke; buses de frameworks
requieren modelos versionados. **Negativo:** llamar `save()` a todos los documentos
sin registro de observadores ni evento. **Límite:** orden, entrega única, reentrancia
y eliminación durante iteración no están garantizados por detectar Observer.

