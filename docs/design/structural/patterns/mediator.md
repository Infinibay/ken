# Mediator

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/mediator.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** mediador, colegas, notificación hacia centro y coordinación hacia colegas.
**Grafo:** varios participantes notifican un centro; este selecciona acciones sobre
otros participantes. Correlacionar evento entrante con llamadas salientes; una
clase muy conectada no basta.

| Lenguaje | Fragmento de coordinación |
|---|---|
| P | `def changed(self, source): self.preview.refresh(source.value); self.save.enable()` |
| JS | `changed(source) { preview.refresh(source.value); save.enable(); }` |
| TS | `changed(source: Widget): void { this.preview.refresh(source.value); this.save.enable(); }` |
| J | `void changed(Widget w){ preview.refresh(w.value()); save.enable(); }` |
| CS | `void Changed(Widget w) { preview.Refresh(w.Value); save.Enable(); }` |
| CPP | `void changed(Widget const& w) { preview.refresh(w.value()); save.enable(); }` |
| G | `func (m *Mediator) Changed(w Widget) { m.Preview.Refresh(w.Value()); m.Save.Enable() }` |
| R | `fn changed(&mut self, value: Value) { self.preview.refresh(value); self.save.enable(); }` |

**Portabilidad:** colegas pueden comunicarse por callbacks/canales; modelar ciclo
sin exigir referencias bidireccionales, difíciles con ownership Rust. **Negativo:**
Facade llamada por clientes que no son colegas coordinados. **Límite:** afirmar que
los colegas nunca se hablan requiere scope cerrado y negación, generalmente parcial.

