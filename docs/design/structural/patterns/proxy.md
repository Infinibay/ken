# Proxy

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/proxy.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** contrato, proxy, subject real y política de acceso/localización/carga.
**Grafo:** el cliente usa el mismo contrato; el proxy decide cuándo/cómo accede al
subject, posiblemente remoto o creado de forma lazy. El branch debe controlar la
llamada pertinente, no estar en otra parte del método.

| Lenguaje | Fragmento de control de acceso |
|---|---|
| P | `def read(self): self.auth.check(); return self.subject.read()` |
| JS | `read() { auth.check(); return subject.read(); }` |
| TS | `read(): string { this.auth.check(); return this.subject.read(); }` |
| J | `public String read(){ auth.check(); return subject.read(); }` |
| CS | `public string Read() { auth.Check(); return subject.Read(); }` |
| CPP | `std::string read() override { auth.check(); return subject->read(); }` |
| G | `func (p Proxy) Read() string { p.Auth.Check(); return p.Subject.Read() }` |
| R | `fn read(&self) -> String { self.auth.check(); self.subject.read() }` |

**Portabilidad:** `check()` puede rechazar por excepción/resultado; no exigir un
`if` visible en el proxy. RPC y proxies generados necesitan modelos externos.
**Negativo:** wrapper sin política observada. **Límite:** se solapa con Decorator;
no inferir autorización solo porque un método se llama `check`.

