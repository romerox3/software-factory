# ADR-0009 · Política de datos por repo y por proveedor

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

- **F0 usa solo tareas públicas** ([06](../06-harness-and-tasks.md) §2.1, decisión del propietario del 2026-10-31). El código de los repos de producto de un **cliente** (el piloto) entra en **F1**, como issues reales tratados por el pipeline, y como PRs minados solo si S3 lo permite.
- El propietario ha levantado la regla «sin repos de clientes en F0–F2» para ese código de producto. Con el cambio, en F0 la regla se cumple de todos modos; la excepción solo se usa desde F1.
- Su política de datos vigente permite, para ese código, **modelos locales, GLM de z.ai y la API de Anthropic**, y excluye dos repos del cliente con material sensible (infraestructura compartida y un repo puente con hosts de bases de datos) [Cierto, política del propietario, fuera de este repo].
- Este repositorio se publicará como Apache-2.0 sin rastro del piloto.

## Opciones

1. **Tareas solo de repos públicos o propios**: no hay riesgo de datos, pero no mide el trabajo real del equipo.
2. **Repos del cliente con la política de proveedores aplicada en el gateway y los datos en un almacén separado**.
3. **Repos del cliente con el mismo repo para todo y limpieza antes de publicar**: depende de no olvidar nada al reescribir el historial.

Se elige la 2.

## Decisión

1. **Clasificación por repo**: cada repo fuente tiene un `data_class` (`public · internal · client-product · client-restricted`). El mapa repo → clase vive en el almacén privado.
2. **Aplicación en el gateway**:
   - cada `data_class` es un equipo de LiteLLM con su lista de modelos permitidos;
   - la virtual key de cada run se crea en el equipo de su clase y no puede llamar a otros modelos [Cierto: una key con `team_id` hereda las restricciones del equipo].
   - Matriz en [02](../02-architecture.md) §8. Para `client-product`: la 5090, z.ai, Anthropic, NaN y OpenRouter (D1, decidido por el propietario el 2026-11-01 y extendido a su política general para ese código). **OpenAI queda fuera.** En OpenRouter, nada de modelos `:free` y las peticiones van con `provider.data_collection: deny`, porque las rutas gratuitas pueden registrar prompts [Probable]. Las cuentas de z.ai y de Anthropic son planes de suscripción, aceptados por el propietario (S14).
3. **Separación física**:
   - tareas, tests ocultos, holdouts, trayectorias, veredictos y la configuración del piloto viven en el **almacén privado** (`factory-pilot-data`), hermano de este repo y sin remoto público;
   - en este repo solo hay esquemas, código genérico, fixtures propios e informes agregados sin contenido del piloto.
4. **Comprobación por construcción**:
   - el hook `.githooks/pre-commit` rechaza commits con patrones de la lista privada (nombres del cliente, hosts, IPs internas);
   - la lista vive en el almacén privado y el hook falla de forma cerrada si no la encuentra.
5. **Repos excluidos**: los dos repos sensibles del cliente no se minan nunca.
6. **Publicación**: antes de hacer público el repo, se escanea **todo el historial** con la lista privada y con un detector de secretos, y una persona lo revisa.

## Consecuencias

- En F0 todas las tareas son `public`. Los brazos usan solo proveedores permitidos para el piloto, para que los resultados se trasladen a F1. A2′ (Codex × OpenAI) queda descartado: OpenAI no está autorizado para el piloto (D1).
- Hasta F1 no hace falta mirror del piloto en Hetzner. S3 y S4 están confirmados (2026-11-01).
- El juez de otro vendor que ve código del piloto es un modelo local, de Anthropic o de NaN. Nunca un modelo `:free` de OpenRouter.
- Los informes publicables usan identificadores de tarea opacos.

## Cómo revertir

Autorizar un proveedor para `client-product` es añadir su alias al equipo del gateway y actualizar la matriz. Quitarlo es lo contrario, y las keys efímeras dejan de tener acceso al expirar.
