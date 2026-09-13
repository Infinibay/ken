# Bridge

Estado: análisis de diseño. [Catálogo](../gof.md) · [Archivo declarativo](../catalog/bridge.toml).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** abstracción, variantes de abstracción, contrato de implementación y sus
implementaciones. **Grafo:** una dimensión contiene/delega en otra independiente;
variantes de ambas pueden combinarse. No exigir herencia en las dos dimensiones.

| Lenguaje | Fragmento de combinación |
|---|---|
| P | `class Circle(Shape):` con `def draw(self): self.renderer.circle(self.radius)` |
| JS | `class Circle extends Shape { draw() { this.renderer.circle(this.radius); } }` |
| TS | `class Circle { constructor(private renderer: Renderer) {} draw() { this.renderer.circle(); } }` |
| J | `class Circle extends Shape { void draw(){ renderer.circle(); } }` |
| CS | `class Circle : Shape { public override void Draw() => renderer.Circle(); }` |
| CPP | `struct Circle : Shape { Renderer& r; void draw() override { r.circle(); } };` |
| G | `type Circle struct { R Renderer }; func (c Circle) Draw() { c.R.Circle() }` |
| R | `struct Circle<R: Renderer> { renderer: R }` con `fn draw(&self) { self.renderer.circle(); }` |

**Portabilidad:** Rust monomorfización no necesita despacho virtual. **Negativo:**
un wrapper aislado con una dependencia. **Límite:** observar dos dimensiones
intercambiables refuerza Bridge; no prueba que evolucionen organizativamente de
forma independiente. Puede coexistir con Strategy.

## Delegación en la abstracción refinada: implementada en IR 1.35.0

La firma runtime-composition existente coloca campo y delegación en la base. Los
casos externos Notification (TypeScript) y Weapon (Java) ponen el comportamiento
en las clases derivadas. Weapon también sitúa el campo en esas clases; Notification
lo hereda. Son estructuras Bridge válidas que la consulta anterior pierde.

Se añadió una variante `refined-composition`, escrita en el mismo TOML, que exige:
una clase derivada, un método suyo que reemplace un slot de la base, una llamada
sobre un campo de implementación y dos subtipos distintos de su contrato. El contrato
de implementación y el de abstracción deben ser distintos. El campo puede estar
declarado en la derivada o resolverse mediante INSTANCE_SLOT en los lenguajes con
ese modelo de herencia. La query expone todos esos roles para revisar el resultado.

La delegación reutiliza relaciones del IR: HAS_METHOD, OVERRIDES, DELEGATES_TO, TYPE e
INSTANCE_SLOT ya distinguen estas ubicaciones. TYPE describe evidencia nominal o
propagación de asignaciones; no demuestra el valor actual. INSTANCE_SLOT conserva
las restricciones existentes de herencia simple Python/JS/TS. No se amplían
silenciosamente a MRO desconocido, propiedades, composición genérica ni embedding Go.

La variante observa dos dimensiones nominales, pero no prueba que una construcción
inyecte la dependencia, que todas las combinaciones se usen ni que sus evoluciones
sean independientes. Lombok permanece sin ejecutar ni expandir: un campo declarado
aporta tipo y uso, no el constructor generado. Esos límites figuran junto a
la query. La variante genérica de Bridge sigue siendo diseño pendiente.

La validación contrasta campo local/heredado, nombres cambiados, contrato ajeno,
una sola implementación, campo sin usar, llamada sobre otro campo y método que no
reemplaza el slot de abstracción. Los controles se escribieron en varios lenguajes;
la evidencia externa se revisó por roles y no sólo por el nombre del directorio.

### Hallazgo de los controles: campos static de C#

El negativo de campo compartido reveló que el frontend busca static en el
variable_declarator, pero C# lo escribe dos niveles más arriba en field_declaration.
Eso clasifica incorrectamente un campo static como de instancia. Se corrigió
leyendo los nodos modifier de esa declaración, sin buscar palabras dentro del
inicializador o comentarios. No añade relaciones al grafo, pero cambia la semántica
del atributo static; se versiona como IR 1.35.0 para invalidar grafos cacheados anteriores.
La variante sólo admite campos con static=false.

### Revisión tras contrastar candidatos externos

La primera prueba sobre el corpus también incluyó decoradores y una fábrica de
prototipos. La variante final exige otra clase de la familia de abstracción,
además de dos implementaciones: un contrato con un único implementador no aporta
dos subtipos de abstracción observados. Esto limita deliberadamente esta firma y no
convierte todas las otras formas de Bridge en negativos semánticos.

Para separar las familias se añadió NOMINAL_ROOT con NOMINAL_ROOT_STATUS. El hecho
relaciona un tipo con la única raíz de su grafo de bases explícitas resueltas. No
incluye bases implícitas (Object/object), compatibilidad estructural, macros ni
herencia runtime. Con bases no resueltas, ciclos, más de una raíz o más de 32
niveles no se publica una raíz exacta. Se comprobaron los mismos cinco lenguajes
nominales del modelo de miembros. Raíces distintas sirven como evidencia positiva
de separación en ese grafo explícito, sin tratar una arista ausente como negación.

Esto permite rechazar Middleware→RequestHandler cuando el propio contrato de
abstracción hereda RequestHandler. La consulta de configuración desde un cliente
sigue pudiendo tener dos familias nominales: queda como ambigüedad de intención
para revisión, sin presentarla como Bridge confirmado ni añadir filtros por nombres.


La variante publica unit, peer, abstraction, operation, slot, access, field,
implementation, first y second. La consulta canónica proyecta unit y deduplica
combinaciones de testigos. Un path INSTANCE_SLOT{0,1} distingue campo local y
slot heredado sin fusionar identidades. Las raíces sólo describen bases explícitas:
no prueban independencia organizativa ni excluyen toda intención alternativa.
La implementación sigue en el [TOML ejecutable](../../../../src/ken/structural/patterns/bridge.toml).
Ver [auditoría, casos pendientes y rendimiento](../../../structural-validation/multilanguage/refined-bridge.md).
