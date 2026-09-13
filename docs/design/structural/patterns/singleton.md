# Singleton

Estado: lazy-guarded y eager-shared implementados; las demás formas siguen
en diseño. [Catálogo de diseño](../gof.md) · [Archivo de diseño](../catalog/singleton.toml)
· [TOML ejecutable](../../../../src/ken/structural/patterns/singleton.toml).

IR 1.45.0 permite que la inicialización null provenga del default de un campo
referencia Java/C#, mediante FIELD_INITIAL_VALUE. Recupera cinco implementaciones
externas revisadas. No atribuye null a campos JS/TS ni anotaciones Python; tipos
declarados y tipos inferidos por escrituras posteriores permanecen separados.
Ver [diseño](../field-initial-values.md) y
[auditoría](../../../structural-validation/multilanguage/field-initial-values.md).

IR 1.44.0 sustituye GUARDS_WRITE como condición suficiente de lazy-guarded.
La variante reutiliza `singleton.lazy_instance`: campo inicializado explícitamente
a null, guardia con polaridad correcta, una escritura y retornos directos en ambas
ramas. Se prueba en Python/Java/JS/TS/C#. Las formas con locks, logging intermedio
y defaults implícitos requieren modelos adicionales; no se prueba exclusividad.
Ver [diseño](../lazy-null-flow.md) y
[auditoría](../../../structural-validation/multilanguage/lazy-null-flow.md).

IR 1.43.0 refuerza la variante eager: exige inventario soportado de constructores
explícitos de instancia, todos privados, y un solo sitio de creación resuelto en
el grafo analizado. Java/C#/TS tienen pruebas; JavaScript conserva la operación
amplia `singleton.shared_instance`. La variante lazy se refuerza después, en IR 1.44.
Ver [diseño actual](../restricted-eager-singleton.md) y
[auditoría](../../../structural-validation/multilanguage/restricted-eager-singleton.md).

IR 1.41.0 incorpora [eager-shared](../eager-singleton.md) en Java/C#/JS/TS y la
operación pública `singleton.shared_instance`. Une inicialización de campo static
con construcción de su propia clase y accessor static que empieza devolviendo
ese slot. La operación amplia no prueba constructor privado, unicidad global, inmutabilidad
ni seguridad concurrente. `module-shared`, holder y primitivas once necesitan
modelos separados. Ver [resultados](../../../structural-validation/multilanguage/eager-singleton.md).

Los fragmentos requieren contexto omitido; no son fixtures compiladas.

**Roles:** almacenamiento compartido, inicializador, accessor, valor cacheado.
**Grafo:** accessor retorna el mismo almacenamiento y existe política de
inicialización única dentro de un ámbito definido. Separar firma lazy guardada,
inicialización eager, singleton de módulo y primitive `once` modelada.

| Lenguaje | Fragmento del mecanismo |
|---|---|
| P | `instance = Service()` en módulo, exportado por `def get(): return instance` |
| JS | `export const instance = new Service();` — alcance de instancia de módulo |
| TS | `export const instance: Service = new Service();` |
| J | `private static final Service INSTANCE = new Service(); static Service get(){ return INSTANCE; }` |
| CS | `static readonly Lazy<Service> instance = new(() => new Service()); public static Service Instance => instance.Value;` |
| CPP | `Service& instance() { static Service value; return value; }` |
| G | `var once sync.Once; var value *Service` con `once.Do(func(){ value=&Service{} })` |
| R | `static INSTANCE: OnceLock<Service> = OnceLock::new();` con `INSTANCE.get_or_init(Service::new)` |

**Portabilidad:** resolver identidad de `Lazy`, `sync.Once`, `OnceLock`, etc.; no
inferir por nombres. **Negativo:** cache indexada por usuario o accessor que crea
siempre otra instancia. **Límite:** alcance de loader/proceso, constructores públicos,
serialización y reflexión impiden afirmar unicidad global. La seguridad concurrente
es otra consulta; la firma singleton no la garantiza.
