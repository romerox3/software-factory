# ADR-0004 · Gateway: LiteLLM frente a Bifrost

- **Estado**: aceptada · **Fecha**: 2026-10-31

## Contexto

El gateway es el único punto que **aplica** presupuesto y política de datos, y la única fuente común de coste para todos los agentes. El propietario ya opera una instancia de LiteLLM con varios proveedores.

## Datos (verificados el 2026-10-31; detalle en [03](../03-reuse-inventory.md))

| Necesidad | LiteLLM OSS | Bifrost OSS |
|---|---|---|
| Presupuesto por virtual key con corte | Sí. Reserva el coste máximo estimado antes de la llamada y concilia después (`budget_reservation.py`) [Cierto] | Sí, HTTP 402. Comprueba antes contra el uso acumulado y cobra después; no se encontró reserva previa [Cierto/Probable] |
| Modelos permitidos por key o equipo | Sí (`models` en key y equipo) [Cierto] | Sí (`allowed_models`) [Cierto] |
| Precios propios (coste sombra) | `model_info.input_cost_per_token`/`output_cost_per_token` [Cierto] | Pricing overrides [Cierto en la documentación] |
| Claude Code (`/v1/messages`) | Sí [Cierto] | `/anthropic` [Cierto] |
| Codex (`/v1/responses` → chat) | Sí, con `use_chat_completions_api: true` [Cierto] | Sin verificar |
| Gasto por key tras la ejecución | `/key/info`, `/spend/logs` [Cierto]; los spend reports son enterprise | No se encontró una API OSS [hueco] |
| Seguridad 2026 | Paquetes PyPI 1.82.7 y 1.82.8 comprometidos el 2026-03-24 ([#24518](https://github.com/BerriAI/litellm/issues/24518)); advisories críticos del 2026-09-30 y el 2026-10-27 [Cierto] | Advisory crítico de RCE vía MCP (2026-09-23) [Cierto] |

**Advertencia**: si el precio de un modelo es 0, LiteLLM se salta las comprobaciones de presupuesto [Cierto en la bandera del código; Probable en que afecte al presupuesto de la key]. **Los precios sombra deben ser > 0** (lo comprueba el spike 1, B5).

## Decisión

**LiteLLM**: la instancia existente del propietario con equipos dedicados (uno por `data_class` más uno para el verificador), **versión fijada por digest de imagen**, nunca `pip install` sin hash. Bifrost queda como plan B.

## Consecuencias

- Una virtual key por ejecución, creada con `team_id`, `max_budget` y `duration` corta. Se revoca al cerrar el run.
- La configuración de precios sombra se versiona (fuera de este repo si incluye hosts) con fuente y fecha por modelo.
- Hay que vigilar los advisories de LiteLLM: es una dependencia crítica de seguridad ([08](../08-risks.md)).

## Cómo revertir

El contrato solo ve `gateway_alias` y una base URL. Cambiar a Bifrost supone reescribir la configuración de modelos, equipos y precios y el lector de gasto por key (que en Bifrost puede no existir en OSS: habría que leer sus logs). Si la instancia compartida da problemas, el primer paso es una instancia LiteLLM propia de la factory.
