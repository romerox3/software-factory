# 04 · Contrato de ejecutor

> **Resumen.** Todo agente pasa por un único contrato JSON (JSON Schema 2020-12 en [`schemas/`](../schemas)). La entrada lleva repo, commit, tarea OpenSpec, presupuesto, ejecutor y alias de modelo. La salida lleva exit, diff, trayectorias, tokens, coste y procedencia. **El diff (calculado en el host), el coste y la trayectoria normalizada los produce el harness**, no el agente. Los cuatro adaptadores (Claude Code, Codex CLI, OpenCode, mini-swe-agent) usan flags leídos en su documentación y su código el 2026-10-31. Los marcados [Probable] los cierra el spike 1.

## 1. Por qué un contrato propio

- Ningún CLI garantiza estabilidad semver de su formato de eventos [Probable, [informe](research/software-factory-open-source.md) capa 2]. Por eso se archiva siempre la salida cruda y se normaliza después.
- Codex no reporta USD [Cierto, el struct `Usage` de `codex exec` no tiene coste]. OpenCode no documenta su esquema de eventos: los tipos de §5.3 se leyeron en su código, no en una documentación con garantías. El coste y los tokens que cuentan salen del **gateway**, que es la única fuente común a todos los agentes ([ADR-0004](adr/0004-gateway.md)).
- Cambiar de agente debe ser un cambio de `executor.name` y `executor.version`, sin tocar el verificador ni las métricas (tesis 4).

## 2. Entrada ([`executor-input.schema.json`](../schemas/executor-input.schema.json))

| Campo | Tipo | Notas |
|---|---|---|
| `run_id`, `attempt` | string, int | El `run_id` es único por intento. `attempt` cuenta los reintentos de la misma tarea en el mismo brazo |
| `repo.url`, `repo.commit` | string, sha de 40 caracteres | `repo.url` de una tarea del piloto es un alias que se resuelve en el almacén privado ([ADR-0009](adr/0009-data-policy-per-repo.md)) |
| `repo.snapshot` | `"fresh-init"` | El workspace es un `git init` nuevo con un único commit del árbol base: sin remotos, tags ni objetos futuros (amenaza T15, [05](05-verification-design.md)) |
| `task` | `{format: "openspec", path, sha256, class, visible_tests[]}`. `class` es `C1`, `C2` o `C4`; la marca de canaria nunca viaja en la entrada | El adaptador **no** lee nada fuera de `proposal.md`, `design.md`, `tasks.md` y `specs/` de la carpeta OpenSpec ([ADR-0005](adr/0005-task-format.md)). Los tests ocultos no forman parte de la tarea |
| `budget` | `{usd, wall_s, tokens?, max_turns?}` | Los `usd` los aplica el gateway (virtual key con `max_budget`). `wall_s` lo aplica el harness (kill del contenedor). `tokens` y `max_turns` son opcionales y solo los aplican los CLIs que tienen un flag para ello (`--max-turns` en Claude Code) |
| `executor` | `{name, version, config_sha}` | Versión semver exacta: el schema rechaza rangos y etiquetas (`latest`, `next`, `^2.1.0`, `2.x`). `config_sha` es el hash de todo lo que configura el brazo |
| `model.gateway_alias` | string | Un alias que apunta a un único modelo inmutable. El gateway comprueba que el alias está permitido para el `data_class` |
| `prompt` | `{template_id, sha256}` | La plantilla base es común a todos los adaptadores (§4) |
| `data_class` | `public · internal · client-product · client-restricted` | Decide qué alias puede usar la virtual key ([ADR-0009](adr/0009-data-policy-per-repo.md)) |
| `abort_path` | string | Por defecto `/workspace/.factory/abort.json` |

## 3. Salida ([`executor-output.schema.json`](../schemas/executor-output.schema.json))

| Campo | Quién lo produce | Notas |
|---|---|---|
| `exit` | El adaptador, con las reglas de §5 | `done · abort_spec_conflict · budget_exceeded · error` |
| `diff` | El **harness, fuera del contenedor** | El workspace se exporta al host al terminar (`docker cp`). En una copia se **sustituye el `.git` del agente por el del snapshot original**, se ejecuta `git add -A -f` (así entran también los ficheros sin trackear y los ignorados) y se calcula `git -c core.attributesFile=/dev/null diff --cached --binary --no-ext-diff --no-textconv <base>`. Así no se usa nada que el agente controle: su `.git`, `.gitattributes`, `diff.external` ni el binario de git del contenedor (amenaza T30). El diff incluye binarios y cambios de modo **para que el verificador pueda rechazarlos**. El `git diff` que el spike 1 genera dentro del contenedor solo vale como smoke |
| `trajectory.raw_*` | El adaptador copia el stream o fichero del CLI | Se archiva sin tocar |
| `trajectory.normalized_uri` | El normalizador → [`trajectory-event.schema.json`](../schemas/trajectory-event.schema.json) | Tipos de evento: `lifecycle, message, reasoning, tool_call, tool_result, usage, error` |
| `tokens` | El gateway; la trayectoria solo si el gateway no tiene el campo | `source` dice de dónde salió |
| `cost` | El gateway: `usd_real` + `usd_shadow` | `agent_reported_usd` (por ejemplo, el `total_cost_usd` de Claude Code) solo sirve para conciliar. Una discrepancia > 5 % marca la ejecución |
| `abort` | El adaptador lee `abort.json` | Obligatorio si `exit = abort_spec_conflict` (lo exige el schema) |
| `provenance` | El harness | Versión del CLI, modelo resuelto por el gateway (en A1 sin gateway, el id completo que fija `--model`), hashes del prompt, la configuración y la tarea, y digest de la imagen. Reimplementa la idea de la procedencia de `agent.sh` de orca-role-hook ([03](03-reuse-inventory.md)) |

Hay ejemplos de entrada y salida para cada adaptador en [`examples/executor/`](../examples/executor), validados con `check-jsonschema` (§7).

## 4. Prompt base común

Todos los adaptadores envuelven la tarea con la misma plantilla (`base-v1`), para que la diferencia entre brazos sea el agente y el modelo, no el prompt. Contenido:

1. El texto de la tarea: `proposal.md` + `specs/` + `tasks.md` de OpenSpec.
2. Las reglas:
   - Los tests existentes y los ficheros de configuración de tests son de **solo lectura**; puedes ejecutarlos, pero cambiarlos invalida la entrega.
   - No hay red, salvo el modelo.
   - No hay historial git útil.
3. **La salida explícita de conflicto**: «Si la especificación y los tests visibles se contradicen, o la tarea no se puede hacer sin violar el spec, escribe `/workspace/.factory/abort.json` con `{"reason", "spec_refs", "test_refs"}` y termina. Abortar con motivo no penaliza». En ImpossibleBench, esta salida bajó la trampa de GPT-5 del 54 % al 9 % en Conflicting-SWE [Probable].
4. Ficheros de instrucciones del repo: los que existan (`AGENTS.md`, `CLAUDE.md`) se dejan tal cual. Claude Code lee `CLAUDE.md` y Codex y OpenCode leen `AGENTS.md` [Probable]. La asimetría se registra en el `config_sha` y, si el repo solo tiene uno de los dos, se crea un symlink al otro **en el snapshot**, nunca en el diff.

## 5. Adaptadores

Los cuatro corren dentro del contenedor de la tarea. La red solo llega al gateway (§6 de [02](02-architecture.md)). `HOME` está vacío, sin configuración del usuario. La única credencial es la virtual key, salvo en la variante (c) de A1 (§5.1).

### 5.1 Claude Code (baseline)

- **Versión fijada**: `@anthropic-ai/claude-code@2.1.316` (npm, verificada el 2026-10-31) [Cierto].
- **Invocación**:
  ```bash
  claude -p "$(cat /workspace/.factory/prompt.md)" \
    --output-format stream-json --verbose \
    --model "$GATEWAY_ALIAS" \
    --max-turns "$BUDGET_MAX_TURNS" --max-budget-usd "$BUDGET_USD" \
    --permission-mode bypassPermissions
  ```
  Todos estos flags están en la [CLI reference](https://code.claude.com/docs/en/cli-reference) [Cierto]. `--max-budget-usd` se comprueba contra la estimación del cliente, no contra la facturación [Cierto]: es un segundo fusible, y el que manda es el del gateway. `stream-json` exige `--verbose` [Cierto]. Los permisos se omiten porque **el aislamiento lo da el contenedor**, no el CLI.
- **Entorno**:
  - **Credencial: la suscripción del propietario** (decisión del 2026-11-01, que sustituye a «nunca OAuth ni suscripción»). El spike B1 prueba tres variantes por orden de preferencia:
    - (a) el gateway guarda el token OAuth (`claude setup-token`) y el sandbox solo recibe `ANTHROPIC_BASE_URL=<gateway>` y la virtual key;
    - (b) el sandbox lleva el token y el gateway lo reenvía, contando el gasto en la virtual key;
    - (c) si ninguna de las dos funciona, el sandbox de A1 sale directamente a `api.anthropic.com` con `CLAUDE_CODE_OAUTH_TOKEN`. Es la única excepción a la salida única de red ([02](02-architecture.md) §2) y la única con una credencial que no caduca con la ejecución. Lleva `--disallowedTools WebSearch,WebFetch`, para que el agente no busque el fix publicado; `--model` con el id completo (regla 6); el fusible en `--max-budget-usd` y `--max-turns`; el coste en el `total_cost_usd` del CLI como coste sombra; y el token borrado de las trayectorias antes de guardarlas.
  - Anthropic limita el token OAuth de los planes a Claude Code y claude.ai [Probable]. Aquí corre el CLI oficial, así que (c) encaja [Suposición], pero (a) y (b) pasan por un proxy y son zona gris [Suposición] (R7).
  - `DISABLE_AUTOUPDATER=1` y `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` [Cierto, [env-vars](https://code.claude.com/docs/en/env-vars)].
  - `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_EXPORTER_OTLP_ENDPOINT=<collector>` y `OTEL_RESOURCE_ATTRIBUTES=run.id=<run_id>,task.id=<task>` [Cierto, [monitoring](https://code.claude.com/docs/en/monitoring-usage)].
- **Sin `--bare`**. `--bare` se salta CLAUDE.md, hooks, MCP y skills [Cierto]. En un contenedor con `HOME` vacío no hay nada del usuario que saltar, y el CLAUDE.md del repo forma parte de la tarea.
- **Trayectoria cruda**: el stdout `stream-json` más el transcript `~/.claude/projects/*/*.jsonl` [Cierto].
- **Resultado**: la última línea `type: "result"`, con `subtype`, `is_error`, `num_turns`, `session_id`, `total_cost_usd`, `usage` y `modelUsage` [Cierto en la documentación del SDK y la página headless; que el CLI emita exactamente los mismos campos es Probable, y lo comprueba el spike 1].
- **Mapeo de `exit`**:

  | Caso | exit |
  |---|---|
  | `abort.json` existe | `abort_spec_conflict` (tiene prioridad) |
  | `subtype = success` | `done` |
  | `error_max_turns` o `error_max_budget_usd` | `budget_exceeded` |
  | `error_during_execution` | `error` |
  | Kill del harness por `wall_s` | `budget_exceeded` |
  | Rechazo del gateway por presupuesto | `budget_exceeded` |

- **Restricción conocida**: el `claude_code()` de inspect_swe rechaza modelos que no son de Anthropic ([issue #177](https://github.com/meridianlabs-ai/inspect_swe/issues/177), abierta) [Cierto]. No afecta al baseline, que usa modelos de Anthropic, pero impide usar Claude Code como harness para modelos no-Anthropic del gateway a través de Inspect.

### 5.2 Codex CLI

- **Versión fijada**: `rust-v0.166.0` (2026-10-29), Apache-2.0 [Cierto].
- **Invocación** ([non-interactive](https://developers.openai.com/codex/noninteractive)):
  ```bash
  codex exec --json -m "$GATEWAY_ALIAS" -s danger-full-access \
    -c model_provider=factory_gateway \
    -o /workspace/.factory/last-message.txt \
    "$(cat /workspace/.factory/prompt.md)"
  ```
  `--json` emite JSONL con los eventos `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.*` y `error` [Cierto]. `--full-auto` ya no existe [Cierto]. Se usa `danger-full-access` porque el sandbox de SO de Codex dentro de Docker es redundante con el contenedor y puede fallar [Probable]. La sintaxis literal de `-c` no se ha visto en la documentación y queda como [Probable]; la alternativa es un `config.toml` montado.
- **Proveedor propio** (`config.toml`):
  ```toml
  [model_providers.factory_gateway]
  name = "factory-gateway"
  base_url = "http://gateway:4000/v1"
  env_key = "FACTORY_GATEWAY_KEY"
  wire_api = "responses"
  ```
  **`responses` es el único valor admitido de `wire_api`** [Cierto, [config reference](https://developers.openai.com/codex/config-reference)]. En consecuencia, el gateway tiene que servir la **Responses API** para GLM. LiteLLM documenta un puente `/v1/responses` → `/chat/completions` para proveedores OpenAI-compatible: se activa con `use_chat_completions_api: true` en el `litellm_params` del modelo, y la documentación cita expresamente a Codex CLI como caso de uso [Cierto, [docs de Responses API](https://docs.litellm.ai/docs/response_api), consultado vía context7 el 2026-10-31]. Queda por comprobar que las tool calls de Codex sobreviven al puente con GLM: lo hace el spike 1, y es un riesgo en [08](08-risks.md).
- **Tokens**: `usage` en `turn.completed`, con `input_tokens`, `cached_input_tokens`, `output_tokens` y `reasoning_output_tokens` [Cierto en el ejemplo de la documentación]. No hay USD.
- **Mapeo de `exit`**:

  | Caso | exit |
  |---|---|
  | `abort.json` existe | `abort_spec_conflict` |
  | Último `turn.completed` sin `error` | `done` |
  | `turn.failed` o `error` | `error` |
  | La causa es un rechazo de presupuesto del gateway | `budget_exceeded` |
  | Kill por `wall_s` | `budget_exceeded` |

### 5.3 OpenCode

- **Versión fijada**: `v1.19.5` (2026-10-28), MIT [Cierto].
- **Invocación**:
  ```bash
  opencode run --format json --model "factory_gateway/$GATEWAY_ALIAS" --auto \
    "$(cat /workspace/.factory/prompt.md)"
  ```
  **Sin `--auto` las peticiones de permiso se rechazan automáticamente** en modo no interactivo [Cierto, `run.ts` del tag v1.19.5]. Eventos JSON: `step_start`, `step_finish`, `text`, `reasoning`, `tool_use` y `error` [Cierto].
- **Proveedor** (`opencode.json`):
  ```json
  {"provider": {"factory_gateway": {"npm": "@ai-sdk/openai-compatible",
     "options": {"baseURL": "http://gateway:4000/v1", "apiKey": "{env:FACTORY_GATEWAY_KEY}"}}}}
  ```
  `@ai-sdk/openai-compatible` + `baseURL` es lo que documenta la página de providers [Cierto]. La sintaxis `{env:…}` es [Probable].
- **Tokens y coste en `step_finish`**: no verificados [Suposición]. Para el contrato no importan, porque salen del gateway.
- **Mapeo de `exit`**: `abort.json` existe → `abort_spec_conflict`; termina sin evento `error` → `done`; evento `error` → `error` o `budget_exceeded`, según la causa del gateway.

### 5.4 mini-swe-agent (control del efecto del harness)

- **Versión fijada**: `v2.4.6` (2026-07-23), MIT [Cierto].
- **Invocación** (`src/minisweagent/run/mini.py`):
  ```bash
  MSWEA_COST_TRACKING=ignore_errors \
  mini -y --exit-immediately -m "openai/$GATEWAY_ALIAS" \
    -t "$(cat /workspace/.factory/prompt.md)" -l "$BUDGET_USD" \
    -o /workspace/.factory/traj.json
  ```
  **Sin `-y` el modo es «confirm» y pide confirmación en cada acción** [Cierto]. `MSWEA_COST_TRACKING=ignore_errors` evita el error con modelos que litellm no tiene registrados [Cierto]. El coste real sale del gateway. El endpoint se pasa con `OPENAI_API_BASE` o `model_kwargs.api_base` en un yaml de configuración [Probable, no probado].
- **Trayectoria**: `.traj.json` con `info.exit_status`, `info.model_stats.instance_cost` y `messages[].extra.response.usage`; formato `mini-swe-agent-1.1` [Cierto].
- **Mapeo de `exit`**: `abort.json` → `abort_spec_conflict`; `info.exit_status` de envío correcto → `done`; límite de coste o de pasos → `budget_exceeded`; excepción → `error`.
- **Por qué está**: es el harness del tablero bash-only de SWE-bench. Con el mismo modelo local que OpenCode, separa el efecto del harness del efecto del modelo (Qwen3-Coder-480B: 55,4 % con mini-swe-agent frente a 69,6 % con OpenHands; [leaderboards.json](https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/master/data/leaderboards.json)) [Cierto, datos de febrero de 2026].

### 5.5 Relación con Harbor

Harbor trae agentes llamados `claude-code`, `codex`, `opencode` y `mini-swe-agent` ([pre-integrated agents](https://github.com/harbor-framework/harbor)) [Cierto]:

- El de Claude Code usa `ANTHROPIC_BASE_URL` y `ANTHROPIC_API_KEY`/`AUTH_TOKEN`.
- El de Codex usa `OPENAI_BASE_URL` y fuerza `model_provider="openai"` para proveedores que no son de OpenAI [Cierto en el código].
- Un agente propio hereda de `BaseInstalledAgent` (`install()`, `run()`, `populate_context_post_run`) [Cierto].

Si el spike 1 confirma que los agentes de Harbor aceptan las versiones y los flags de arriba, **el adaptador es una subclase fina que solo fija versión, flags, `abort.json` y la salida del contrato**. Si no, se escribe la subclase completa con esta especificación.

**Qué ata a Harbor y qué habría que reescribir para salir**: las subclases de `BaseInstalledAgent` (invocación), el lector de `result.json` (tiempos) y el conversor OpenSpec → tarea de Harbor. No dependen de Harbor ni el contrato (schemas), ni el cálculo del diff (se hace en el host, §3), ni el coste (gateway), ni el normalizador, ni el verificador. Con Inspect habría que reescribir esas tres piezas: unos 2–4 días [Suposición].

## 6. Normalización

| Formato crudo | Origen | Mapeo a `trajectory-event` |
|---|---|---|
| `claude-stream-json` | stdout de `claude -p --output-format stream-json` | `assistant` → `message`/`tool_call` (bloques `tool_use`), `user` con `tool_result` → `tool_result`, `result` → `usage` + `lifecycle` |
| `codex-exec-jsonl` | stdout de `codex exec --json` | `item.*` con `command_execution` → `tool_call`/`tool_result`, `agent_message` → `message`, `reasoning` → `reasoning`, `turn.completed.usage` → `usage` |
| `opencode-run-json` | stdout de `opencode run --format json` | `tool_use` → `tool_call` + `tool_result`, `text` → `message`, `reasoning` → `reasoning`, `step_finish` → `usage` (si trae tokens) |
| `mini-traj-json` | `-o traj.json` | `messages[]` por rol; las acciones bash del asistente → `tool_call`, la observación siguiente → `tool_result`, `extra.response.usage` → `usage` |

El normalizador es tolerante: un evento desconocido se emite como `kind: "lifecycle"` con `tool_raw` igual al tipo original, y se cuenta en un contador de «eventos no mapeados por versión». Si ese contador sube tras un cambio de versión, hay que revisar el mapeo.

## 7. Validación

```bash
uv run --with check-jsonschema check-jsonschema --check-metaschema schemas/*.json
for n in claude-code codex opencode mini-swe-agent; do
  uv run --with check-jsonschema check-jsonschema --schemafile schemas/executor-input.schema.json  examples/executor/$n.input.json
  uv run --with check-jsonschema check-jsonschema --schemafile schemas/executor-output.schema.json examples/executor/$n.output.json
done
```

```bash
uv run --with jsonschema python -I -c "import json,jsonschema; s=json.load(open('schemas/trajectory-event.schema.json')); [jsonschema.validate(json.loads(l), s) for l in open('examples/executor/trajectory.example.jsonl')]"
```

El 2026-10-31 validaron los 3 schemas contra el metaschema, los 8 ficheros de ejemplo y las 4 líneas del JSONL de trayectoria. Además, 7 casos negativos son rechazados (versión `latest`, `^2.1.0` o `2.x`, sha corto, clase de canaria en la entrada, aborto sin objeto `abort`, coste con origen `agent`) [Cierto, ejecución local]. Los ejemplos de Claude Code y Codex usan `data_class: client-product`; los de OpenCode y mini-swe-agent, `public`.

## Decisiones abiertas

- **Tool calls de Codex a través del puente Responses→chat de LiteLLM con GLM**. Plan B único, el mismo en [ADR-0001](adr/0001-harness-runner.md), [06](06-harness-and-tasks.md) y [08](08-risks.md): si falla B3 del spike, el brazo A2 se sustituye por **OpenHands SDK × GLM**, que mantiene el modelo fijo para comparar ejecutores. No hay A2′ (Codex × OpenAI): OpenAI no está autorizado (D1, [09](09-open-questions.md)).
- Si la normalización debe mapear a OTel GenAI semconv además del esquema propio. Las semconv no tienen estado de estabilidad declarado [Cierto, informe capa 8], y se pospone a F2.
- `tokens` en `budget` solo lo aplican los CLIs que tienen un flag para ello. Queda por decidir si el harness corta por tokens leyendo el gasto del gateway en vivo.
