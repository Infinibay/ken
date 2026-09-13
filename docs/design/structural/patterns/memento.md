# Memento

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/memento.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** originador, estado, snapshot, caretaker y restauración. **Grafo:** save
lee estado y lo transfiere al snapshot; caretaker conserva ese resultado; restore
consume sus valores para escribir estado del mismo originador/contrato.

| Lenguaje | Fragmento de save/restore |
|---|---|
| P | `def save(self): return Snapshot(self.text)` / `def restore(self, s): self.text = s.text` |
| JS | `save() { return { text: this.text }; } restore(s) { this.text = s.text; }` |
| TS | `save(): Snapshot { return {text: this.text}; } restore(s: Snapshot) { this.text=s.text; }` |
| J | `Snapshot save(){ return new Snapshot(text); } void restore(Snapshot s){ text=s.text(); }` |
| CS | `Snapshot Save() => new(text); void Restore(Snapshot s) { text=s.Text; }` |
| CPP | `Snapshot save() const { return {text}; } void restore(Snapshot const& s) { text=s.text; }` |
| G | `func (e Editor) Save() Snapshot { return Snapshot{e.Text} }; func (e *Editor) Restore(s Snapshot) { e.Text=s.Text }` |
| R | `fn save(&self) -> Snapshot { Snapshot(self.text.clone()) } fn restore(&mut self, s: Snapshot) { self.text=s.0; }` |

**Portabilidad:** snapshot puede ser valor inmutable, record, tuple o blob serializado.
**Negativo:** método que escribe un campo desde cualquier parámetro sin flujo desde
un snapshot creado. **Límite:** encapsulación y copia profunda son propiedades
separadas; snapshot que comparte listas mutables puede ser defectuoso.

