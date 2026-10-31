# ADR-0009 · Política de datos por repo y por proveedor

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

- Las tareas de F0 se minan de los repos de producto de un **cliente** (el piloto).
- El propietario ha levantado la regla «sin repos de clientes en F0–F2» para ese código de producto.
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
   - Matriz en [02](../02-architecture.md) §8. Para `client-product`, solo la 5090, z.ai y Anthropic. **OpenAI y los proveedores gratuitos quedan fuera hasta que el propietario los autorice.** Que la cuenta de z.ai sea de API de pago por token y no un plan de suscripción está sin confirmar ([09](../09-open-questions.md) S14).
3. **Separación física**:
   - tareas, tests ocultos, holdouts, trayectorias, veredictos y la configuración del piloto viven en el **almacén privado** (`factory-pilot-data`), hermano de este repo y sin remoto público;
   - en este repo solo hay esquemas, código genérico, fixtures propios e informes agregados sin contenido del piloto.
4. **Comprobación por construcción**:
   - el hook `.githooks/pre-commit` rechaza commits con patrones de la lista privada (nombres del cliente, hosts, IPs internas);
   - la lista vive en el almacén privado y el hook falla de forma cerrada si no la encuentra.
5. **Repos excluidos**: los dos repos sensibles del cliente no se minan nunca.
6. **Publicación**: antes de hacer público el repo, se escanea **todo el historial** con la lista privada y con un detector de secretos, y una persona lo revisa.

## Consecuencias

- El brazo «Codex con modelo de OpenAI» no existe en F0 para tareas del piloto. Codex corre con GLM.
- El juez de otro vendor que ve código del piloto es un modelo local o de Anthropic, nunca un proveedor gratuito.
- Los informes publicables usan identificadores de tarea opacos.

## Cómo revertir

Autorizar un proveedor para `client-product` es añadir su alias al equipo del gateway y actualizar la matriz. Quitarlo es lo contrario, y las keys efímeras dejan de tener acceso al expirar.
