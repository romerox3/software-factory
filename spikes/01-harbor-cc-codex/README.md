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
1. Una API key de Anthropic **de pago** (no de suscripción), dada de alta como modelo en el gateway.
2. Una clave de z.ai (GLM) dada de alta en el gateway, con `use_chat_completions_api: true` para el puente Responses.
3. Una clave de LiteLLM con permiso para crear virtual keys en un equipo `factory-public`.

**Criterios** (cada uno cierra un punto concreto del diseño):

| # | Prueba | Cierra |
|---|---|---|
| B1 | `harbor run -a claude-code -m <alias>` con `ANTHROPIC_BASE_URL=<gateway>` y una virtual key con `max_budget = 0.50` resuelve `calc-rounding` | Tesis 4: Claude Code a través del gateway con API key |
| B2 | El `total_cost_usd` de Claude Code frente al gasto de la virtual key: discrepancia < 5 % | M1 (conciliación) |
| B3 | `harbor run -a codex` con un proveedor `factory_gateway` y `wire_api = "responses"` contra GLM resuelve la tarea y sus tool calls funcionan | El brazo A2 de F0 ([06](../../docs/06-harness-and-tasks.md)) |
| B4 | Una virtual key con `max_budget = 0.01` corta la ejecución, y el adaptador lo mapea a `budget_exceeded` | Presupuesto por ejecución |
| B5 | Un modelo con precio sombra 0 frente a > 0 en `model_info`: ¿se corta el presupuesto? | Advertencia de [02](../../docs/02-architecture.md) §7 |
| B6 | En la torre Linux: `network-probe` con `no-network` → reward 1 (todo inalcanzable salvo lo permitido) | Red del sandbox |

Coste estimado de la parte B: < 2 USD de Anthropic + la cuota de z.ai [Suposición].

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
