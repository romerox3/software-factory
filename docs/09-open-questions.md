# 09 · Supuestos y preguntas abiertas

> **Resumen.** Recoge los supuestos con los que se escribió el plan, las preguntas que debe responder el propietario y los hallazgos de la revisión independiente que no se incorporaron, cada uno con su argumento. Las tres decisiones que bloquean más trabajo están en §1. Ningún supuesto bloquea el arranque de F0-01, F0-02, F0-06, F0-08, F0-09 ni F0-11.

## 1. Decisiones que necesita tomar el propietario

| # | Decisión | Opciones | Qué bloquea | Recomendación |
|---|---|---|---|---|
| D1 | **¿Pueden ver código del piloto OpenAI, NaN u OpenRouter?** | Ninguno (por defecto) · solo OpenAI con retención cero · otros | El brazo «Codex con modelo de OpenAI». Si no hay autorización, Codex corre con GLM ([ADR-0009](adr/0009-data-policy-per-repo.md)) | Ninguno en F0. Codex × GLM es suficiente para comparar ejecutores |
| D2 | **Licencia de orca-role-hook** | Pedir a Felipe Castaño Apache-2.0 o MIT · no pedir nada | Solo un eventual port de `verify_task.py` o `crosscheck.sh`. El diseño no lo necesita ([ADR-0007](adr/0007-orca-role-hook.md)) | Pedirla de todos modos para poder citar o portar sin dudas. Preguntarle además si los commits firmados con su correo de Vicomtech (3, todos en `bin/agent.sh`) tienen alguna reclamación de su empleador. Ningún otro activo candidato tiene commits de ese correo |
| D3 | **¿Aceptas que F3 dependa del volumen (≥ 150 cambios por clase) y no del calendario?** | Sí · bajar el umbral (por ejemplo, 60 cambios → cota ~5 %) | El criterio de [ADR-0008](adr/0008-gates-and-auto-merge.md) | Sí. Bajar el volumen sube la cota de regresiones aceptada, y eso es una decisión de riesgo, no técnica |

## 2. Supuestos con los que se escribió el plan

| # | Supuesto | Origen | Cómo se cierra |
|---|---|---|---|
| S1 | El repo es Apache-2.0, privado durante la construcción y público al validarse, sin rastro del piloto | Respuesta del propietario (2026-10-31) | — |
| S2 | Las tareas salen de los tres repos de producto del piloto; se levanta la regla «sin repos de clientes» para ellos | Respuesta del propietario (2026-10-31) | — |
| S3 | **Uso del código del cliente como dataset de evaluación**: la política verificada del propietario cubre qué proveedores de modelos pueden ver ese código, **no su uso como benchmark**, ni guardar tareas, holdouts y trayectorias derivadas | Hueco detectado | El propietario confirma que el contrato con el cliente lo permite |
| S4 | **El evaluador en Hetzner puede alojar código del cliente** (mirror, tests ocultos) | Hueco detectado | El propietario confirma que el servidor está dentro del perímetro permitido |
| S5 | Sin tope mensual. Presupuesto por ejecución + coste sombra + alarma a los 300 USD de gasto real en Anthropic | Respuesta del propietario | — |
| S6 | El baseline Claude Code usa **Sonnet** (versión vigente, fijada) | Juicio propio: el prompt fija el agente, no el modelo | El propietario lo confirma o pide Opus |
| S7 | Documentación en español; código e identificadores en inglés | Respuesta del propietario | — |
| S8 | **Tipo del servidor Hetzner** (dedicado con `/dev/kvm` o Cloud sin virtualización anidada) | Desconocido | Solo afecta al [ADR-0003](adr/0003-sandbox.md) en F2 |
| S9 | **Qué es «aitire»** (proveedor del gateway mencionado por el propietario) | Desconocido | Clasificarlo en la matriz de [02](02-architecture.md) §8 antes de habilitarlo |
| S10 | La instancia compartida del gateway admite equipos dedicados sin interferir con otros usos | Juicio propio | F0-03 |
| S11 | La torre tiene un kernel con nftables `fib inet`, así que el control de egress de Harbor funcionará allí | [Probable]: falla en macOS | F0-07 |
| S12 | El modelo local es de clase Qwen3.6-35B-A3B y cabe cuantizado con 64k de contexto en 32 GB | [Suposición] | F0-03 |
| S13 | El minado del piloto rinde ~20 % de los PRs que tocan tests, como SWE-bench | [Probable] por analogía | F0-05 |
| S14 | **La cuenta de z.ai que usa el gateway es de API de pago por token**, no un plan de suscripción («coding plan»). El 429 con > 6 concurrentes apunta a un plan con límites [Suposición]. Si es un plan, A2, A3, A6 y los peones chocan con la regla 2 de `CLAUDE.md` («nunca planes de consumo en ejecuciones automáticas») | Revisión independiente | El propietario confirma el tipo de cuenta y, si es un plan, que sus términos permiten uso automatizado; si no, cambiar a la API de pago (R21) |
| S15 | `/spend/logs` por key está en LiteLLM OSS y da los tokens por petición | [Probable] | F0-03 |

## 3. Evidencia nueva contra una tesis (pide validación)

- **Tesis 8, DOT compatible con Attractor**. A fecha del 2026-10-31:
  - el spec Attractor no tiene commits desde marzo;
  - Tracker marca su parser DOT como deprecado en favor de `.dip`, que no tiene licencia;
  - Kilroy está parado desde abril.

  El plan **mantiene DOT** como formato propio, simple y versionado, pero la razón ya no es la portabilidad entre motores ([ADR-0002](adr/0002-orchestrator.md) §4). **Pregunta**: ¿se mantiene la tesis con la razón cambiada, o se cambia el formato del pipeline (por ejemplo, YAML propio)?

## 4. Correcciones al informe de investigación (verificadas en vivo el 2026-10-31)

| Dato del informe | Dato verificado |
|---|---|
| HumanLayer ACE: Apache-2.0, «fork de prompts» | **Sin licencia**: solo referencia |
| Mastra Factory: Apache-2.0 | **Sin licencia** |
| Tracker: «fork/piloto», motor DOT más completo | El parser DOT está **deprecado** (`.dip`); 2 contribuidores principales |
| Kilroy: activo | Último push del **2026-04-27** |
| `anthropic-experimental/sandbox-runtime` | Ahora es `anthropics/sandbox-runtime` |
| `e2b-dev/infra` | Redirige a `e2b-dev/runtime` |
| qodo pr-agent: conflicto MIT/AGPL | `The-PR-Agent/pr-agent`, **MIT** |
| gh-aw: «versiones retiradas» | Es un advisory, no una retirada de releases, y hay 15 advisories entre agosto y octubre |
| `claude -p --output-format json` devuelve `total_cost_usd` [Suposición en el informe] | Documentado en la página headless [Cierto] |
| Codex: proveedor propio con `wire_api` chat o responses | Solo `responses` [Cierto] |

## 5. Hallazgos de la revisión independiente no incorporados

La revisión independiente (un subagente Sonnet que solo recibió las tesis, los criterios de contenido y los documentos) dio 25 hallazgos el 2026-10-31. **Se incorporaron 20 enteros y 5 en parte.** Entre los incorporados están el canal de feedback con lista blanca (T28), el sandbox de la fase de verificación (T29), el diff calculado en el host (T30), las canarias indistinguibles con la tarea-canaria como unidad, la no-inferioridad con Δ, el arranque de M8, la provisión del verificador (F0-21), las clases C3–C5, el brazo A6, la salida de F3 por M4 y M5, y las filas de GitHub y Hetzner.

Lo que no se incorporó, o solo en parte:

| Hallazgo | Qué se hizo | Argumento |
|---|---|---|
| #14 · Añadir un brazo de un segundo proveedor | Solo S14 y R21 | A4 y A5 (modelo local) ya son un segundo proveedor en la comparación. Que los peones dependan de z.ai afecta a cómo se implementa F0, no al sistema que se mide: si z.ai cae, los peones pasan a otro modelo del gateway, siempre con código público |
| #13 · «≥ 95 % de salidas válidas» mide formato y no calidad | Se mantiene, etiquetado como salud del harness, y se añade el techo de `error_infra` | Es intencionado: F0 tiene que demostrar que el harness produce datos utilizables antes de leer la calidad. La calidad la miden los criterios de falsos `accept` y de pass@1 |
| #23 · Los ADR no tienen resumen ni «Decisiones abiertas» | Se añadió «Opciones» a los 5 que no la tenían | El encargo fija el formato de los ADR (contexto, opciones, decisión, consecuencias, cómo revertir). El criterio de resumen y «Decisiones abiertas» es de los documentos 00–09 |
| #24 · A2 frente a A3 queda confundido por el puente Responses | Se declara que el puente forma parte del brazo A2 | No se puede separar: Codex solo admite `wire_api = "responses"`. El efecto del ejecutor sin puente con GLM fijo lo da A6 frente a A3 |
| #17 · F0-02 construye el servicio de emisión aunque 02 lo condicionaba | Se quitó la condición en 02 | El revisor no pudo comprobarlo, pero el rol de *team admin* es de pago en LiteLLM (código leído en v1.86.2, `notas:conocimiento/infra/litellm-gateway-que-se-puede-hacer.md`) [Cierto], así que el servicio hace falta siempre |

## Decisiones abiertas

- D1, D2 y D3 de §1.
- S3 y S4 deben confirmarse antes de F0-17 (minar las tareas reales).
- S14 debe confirmarse antes de F0-18 (la matriz usa z.ai en tres brazos).
