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

*(Se completa tras la revisión de la sección 9.4 del encargo: cada hallazgo no incorporado, con su argumento.)*

## Decisiones abiertas

- D1, D2 y D3 de §1.
- S3 y S4 deben confirmarse antes de F0-17 (minar las tareas reales).
