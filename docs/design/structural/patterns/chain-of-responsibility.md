# Chain of Responsibility

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/chain-of-responsibility.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** handler, siguiente handler, request, criterio de manejo y cliente.
**Grafo:** un handler procesa o reenvía la misma request a otro del contrato;
ensamblado de varios handlers refuerza la cadena. Debe haber terminación local o
posibilidad de continuar; no basta delegación condicional cualquiera.

| Lenguaje | Fragmento de paso de cadena |
|---|---|
| P | `def handle(self, req): return self.process(req) if self.accepts(req) else self.next.handle(req)` |
| JS | `handle(req) { return accepts(req) ? process(req) : next.handle(req); }` |
| TS | `handle(req: Request): Reply { return this.accepts(req) ? this.process(req) : this.next.handle(req); }` |
| J | `Reply handle(Request r){ return accepts(r) ? process(r) : next.handle(r); }` |
| CS | `Reply Handle(Request r) => Accepts(r) ? Process(r) : next.Handle(r);` |
| CPP | `Reply handle(Request const& r) override { return accepts(r) ? process(r) : next->handle(r); }` |
| G | `func (h Handler) Handle(r Request) Reply { if h.Accepts(r) { return h.Process(r) }; return h.Next.Handle(r) }` |
| R | `fn handle(&self, r: &Request) -> Reply { if self.accepts(r) { self.process(r) } else { self.next.handle(r) } }` |

**Portabilidad:** middleware funcional puede envolver `next` capturado en vez de
campo. **Negativo:** proxy que verifica permisos y siempre llama al mismo subject,
sin responsabilidad alternativa o topología de cadena. **Límite:** pipelines que
siempre ejecutan todos los pasos son variante distinta, no igual por nombre.

