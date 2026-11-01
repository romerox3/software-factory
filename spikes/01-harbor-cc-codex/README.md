# Spike 01 · Harbor ejecuta tareas propias (y, pendiente, Claude Code y Codex a través del gateway)

> **Resumen.** Ejecutado el 2026-10-31 en el portátil del propietario (macOS, Docker Desktop 29.1.3) con `uvx --from harbor==0.25.0`. **Parte A (sin LLM): hecha.** El formato de tarea propio funciona, el agente `oracle` obtiene reward 1 y `nop` reward 0, y el diff sale como artefacto del verificador. **Hallazgo clave**: en Docker, Harbor solo aplica `no-network` o `allowlist` con un sidecar nftables cuando el kernel del daemon lo soporta. En Docker Desktop para macOS no lo soporta, y Harbor **rechaza la tarea** (falla de forma cerrada). **Parte B (Claude Code y Codex a través del gateway): pendiente** de las claves (ver §4). Duración de la parte A: ~40 min.

## 1. Qué se probó

| Prueba | Tarea | Agente | Resultado |
|---|---|---|---|
| A1 | `calc-rounding` con `network_mode = "allowlist"` | `oracle` | **Rechazada**: `ValueError: network_mode='allowlist' is not supported by EnvironmentType.DOCKER environment` [Cierto, ejecución local] |
| A2 | Las dos tareas con `network_mode = "no-network"` | `oracle` | **Rechazada** con el mismo error para `no-network` [Cierto] |
| A3 | `calc-rounding` con `network_mode = "public"` | `oracle` | reward = **1** (el gold pasa los tests ocultos) [Cierto] |
| A4 | Ídem | `nop` | reward = **0** (sin cambio, los F2P ocultos fallan) [Cierto] |
| A5 | Exportar el diff | — | `tests/test.sh` escribe `git diff` en `/logs/verifier/diff.patch`, que Harbor copia a `<job>/<trial>/verifier/diff.patch` en el host [Cierto] |

## 2. Por qué falla la red en macOS

En el código de Harbor 0.25.0 (`harbor/environments/docker/docker.py`), las capacidades `disable_internet` y `network_allowlist*` del entorno Docker valen `_enable_egress_control`. Ese valor solo es cierto si se cumplen tres condiciones:
- el contenedor no es Windows;
- la tarea pide control de egress;
- `_egress_control_kernel_support()` comprueba, ejecutando un contenedor, que **el kernel del daemon soporta reglas nftables `fib inet`**.

Cuando no se cumplen, `validate_network_policy_support` lanza un error y la tarea no corre [Cierto, código leído]. El control se implementa con un sidecar (`harbor-docker-egress-control-sidecar`) definido en `docker-compose-egress-control.yaml` [Cierto].

**Consecuencias para el diseño**:
- En la torre Linux es probable que funcione [Probable]. Hay que comprobarlo allí con la tarea `network-probe` antes de F0-07.
- Aunque funcione, el [02](../../docs/02-architecture.md) §6 mantiene la regla en `DOCKER-USER` del host como defensa en profundidad. Las issues de red de Harbor siguen abiertas (#3611, #3992, #3821).
- El fallo cerrado es el comportamiento correcto: nunca corre una tarea con una política de red que no se pueda aplicar.

## 3. Formato y resultados de Harbor (verificado)

- La estructura `instruction.md`, `task.toml` (schema 1.4), `environment/Dockerfile`, `solution/solve.sh` y `tests/test.sh` funciona con un repo copiado en la imagen y un commit base creado en el Dockerfile [Cierto].
- `result.json` de cada trial tiene estas claves: `agent_result` (`n_input_tokens`, `n_cache_tokens`, `n_output_tokens`, `cost_usd`, `model_usage`), `verifier_result.rewards`, `verifier_environment_mode`, `exception_info`, y los tiempos de `environment_setup`, `agent_setup`, `agent_execution` y `verifier` [Cierto]. Cierra el hueco de «layout de resultados» del informe del investigador.
- El agente integrado `claude-code` expone `--max-turns`, `--max-budget-usd` y `--permission-mode` (por defecto `bypassPermissions`), y lee `ANTHROPIC_BASE_URL` [Cierto, `agents/installed/claude_code.py`]. El de `codex` lee `OPENAI_BASE_URL` y la tabla `model_providers` de su configuración nativa, incluido `wire_api` [Cierto, `agents/installed/codex.py`]. Esto apoya que los adaptadores de [04](../../docs/04-executor-contract.md) sean configuración sobre los agentes de Harbor.

## 4. Parte B pendiente: qué hace falta y qué se medirá

**Necesito del propietario** (el spike no las lee de configuraciones existentes):
1. Un token de la suscripción de Anthropic (`claude setup-token`). El propietario no tiene API de pago y acepta la suscripción (2026-11-01). B1 prueba primero que el gateway lo guarde o lo reenvíe y, si no funciona, la salida directa ([04](../../docs/04-executor-contract.md) §5.1).
2. Una clave de z.ai (GLM) dada de alta en el gateway, con `use_chat_completions_api: true` para el puente Responses.
3. Una clave de LiteLLM con permiso para crear virtual keys en un equipo `factory-public`. El orquestador tiene acceso al gateway desde el 2026-11-01.

**Criterios** (cada uno cierra un punto concreto del diseño):

| # | Prueba | Cierra |
|---|---|---|
| B1 | `harbor run -a claude-code -m <alias>` resuelve `calc-rounding` con la suscripción, probando las variantes (a), (b) y (c) de [04](../../docs/04-executor-contract.md) §5.1 por ese orden. En (a) y (b), con `ANTHROPIC_BASE_URL=<gateway>` y una virtual key con `max_budget = 0.50` | Qué variante usa A1 |
| B2 | El `total_cost_usd` de Claude Code frente al gasto de la virtual key: discrepancia < 5 % | M1 (conciliación) |
| B3 | `harbor run -a codex` con un proveedor `factory_gateway` y `wire_api = "responses"` contra GLM resuelve la tarea y sus tool calls funcionan | El brazo A2 de F0 ([06](../../docs/06-harness-and-tasks.md)) |
| B4 | Una virtual key con `max_budget = 0.01` corta la ejecución, y el adaptador lo mapea a `budget_exceeded` | Presupuesto por ejecución |
| B5 | Un modelo con precio sombra 0 frente a > 0 en `model_info`: ¿se corta el presupuesto? | Advertencia de [02](../../docs/02-architecture.md) §7 |
| B6 | En la torre Linux: `network-probe` con `no-network` → reward 1 (todo inalcanzable salvo lo permitido) | Red del sandbox |
| B7 | Porcentaje de ventana por ejecución en los dos planes: `percentage` de `TOKENS_LIMIT` de z.ai antes y después de B3 (no `model-usage`, que no registra el coding plan), y el uso de la suscripción de Anthropic antes y después de B1 | S18: cuota de la matriz |

Coste estimado de la parte B: sin gasto real; unos pocos puntos de la ventana de cada plan [Suposición].

### Resultados parciales de la parte B (2026-11-01, contra el gateway real)

| # | Resultado | Consecuencia |
|---|---|---|
| B4 | Una key con `max_budget = 1e-05` acepta la primera llamada y rechaza las siguientes con **HTTP 429** y `error.type = "budget_exceeded"` [Cierto]. El corte llega una petición tarde: la llamada que cruza el límite se sirve (gasto 1,01e-05 frente a 1e-05) | El adaptador mapea `budget_exceeded` por `error.type`, no por el código, porque un 429 también puede ser un límite de ritmo. El presupuesto de la key es un fusible con un exceso de hasta una petición |
| B5 | Ningún modelo de los equipos de la factory tiene precio 0. Los que lo tienen en el gateway (los `:free` de OpenRouter y los de audio o imagen de NaN) quedan fuera de los equipos [Cierto] | El problema de que «un coste 0 se salta el presupuesto» se evita por construcción. El smoke de F0-03 comprueba que ningún modelo de un equipo de la factory tiene precio 0 |
| B6 | En la torre (Linux, kernel 7.0, Docker 29.7.2), `network_mode = "allowlist"` con el nombre del gateway: el gateway es alcanzable, y example.com, `api.github.com` y otra web de la misma CDN no lo son. Reward 1 [Cierto] | La red del sandbox queda resuelta con el sidecar de Harbor, que filtra por SNI ([02](../../docs/02-architecture.md) §6). DNS hacia el resolvedor sigue abierto (riesgo residual) |
| B3 | Directo contra el gateway: `/v1/responses` con una herramienta sobre `zai/glm-5.3-flash` y `zai/glm-5.3` devuelve `function_call` y acepta el `function_call_output` del turno 2 [Cierto]. Con Harbor en la torre: **Codex 0.166.0 × `glm-5.3-flash` resuelve `calc-rounding` con reward 1**, 40,7 K tokens de entrada, 3,1 K de salida y 0,0069 USD de coste sombra [Cierto]. Hicieron falta tres arreglos: (1) Codex instalado en la imagen, porque con la red en lista blanca Harbor no puede instalarlo en el setup; (2) un wrapper de `codex --version` que descarta stderr, porque Codex avisa de `Cross-device link` y Harbor toma ese aviso por la versión y reinstala; (3) `-m openai/zai/glm-5.3-flash`, porque con `zai/…` Harbor lo lee como proveedor `zai` y no le pasa `OPENAI_API_KEY` | El brazo A2 es viable sin el plan B (R10 no se materializa). Los adaptadores (F0-13) instalan el CLI en la imagen fijado por versión y con el wrapper |
| B7 (z.ai) | `TOKENS_LIMIT` del coding plan: 1 % antes y 1 % después de B3 (unos 47 K tokens en total) [Cierto]. El porcentaje es entero, así que la ventana de 5 h tiene más de ~4,7 M tokens, en línea con la estimación anterior de 26–40 M [Probable] | Una ejecución pequeña cuesta < 0,2 % de la ventana. El dato que decide S18 es el de las tareas reales (F0-17), que son mucho más grandes |
| B1 | Variante (a): el gateway guarda el token OAuth en su `.env` y el sandbox solo recibe `ANTHROPIC_BASE_URL` y una virtual key de 0,50 USD. `harbor run -a claude-code -m anthropic/claude-sonnet-5-5` con Claude Code 2.1.316 instalado en la imagen: **reward 1**, 3 peticiones (todas a `claude-sonnet-5-5`, con `ANTHROPIC_DEFAULT_HAIKU_MODEL` apuntando al mismo modelo), 51,2 K tokens de entrada (33,7 K leídos de caché) y 686 de salida [Cierto]. Anthropic devuelve 429 al token si la petición no lleva el system prompt de identidad de Claude Code, y 200 si lo lleva [Cierto] | A1 usa la variante (a); (b) y (c) no hacen falta. Por ese mismo 429, una key de otro proyecto sin restricción de modelos no puede gastar la suscripción desde otro cliente |
| B2 | `total_cost_usd` 0,0541 USD frente a 0,0575 USD de gasto de la key: un **5,9 %, por encima del 5 %**. La diferencia es exactamente 33 667 tokens leídos de caché × 1e-7: el CLI cobra la lectura de caché a 0,10 USD/MTok y el gateway, a 0,20 USD/MTok, que es el precio de lista [Cierto, aritmética] | M1 toma el gasto del gateway. `total_cost_usd` queda como dato secundario |
| B7 (Anthropic) | No medido: el uso de la suscripción no se puede leer por API sin otra credencial | Se mide con la ventana de uso de claude.ai durante F0-18 |

## 5. Cómo reproducir la parte A

```bash
S=$(mktemp -d)
cp -R spikes/01-harbor-cc-codex/tasks/calc-rounding "$S/"
sed -i '' 's/network_mode = "no-network"/network_mode = "public"/' "$S/calc-rounding/task.toml"   # solo en macOS
uvx --from harbor==0.25.0 harbor run -p "$S" -a oracle -o "$S/jobs" --job-name oracle
uvx --from harbor==0.25.0 harbor run -p "$S" -a nop    -o "$S/jobs" --job-name nop
cat "$S"/jobs/*/calc-rounding__*/verifier/reward.txt     # 1 y 0
```

Las tareas del repo se quedan con `no-network` para que en la torre fallen de forma cerrada si la red no se puede aplicar.

## Decisiones abiertas

- Si la parte B confirma B1–B4, el [ADR-0001](../../docs/adr/0001-harness-runner.md) queda en «Harbor». Si B3 falla, el brazo A2 cambia ([04](../../docs/04-executor-contract.md), decisiones abiertas).
- Si B6 falla en la torre, la red se aplica solo en el host y Harbor corre con `public` dentro de la red `factory-egress`. Hay que comprobar que Harbor permite fijar la red de compose.
