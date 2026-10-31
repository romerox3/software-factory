# ADR-0001 · Runner del harness: Harbor frente a Inspect

- **Estado**: aceptada con condición (falta la parte B del spike 1) · **Fecha**: 2026-10-31

## Contexto

El harness ejecuta la matriz tareas × brazos × repeticiones con agentes CLI en contenedores. Según la tesis 1, el runner paralelo se reutiliza y no se construye. Los candidatos son Harbor (Apache-2.0, v0.25.0) e Inspect AI (MIT, 0.3.287) con inspect_swe (MIT, 0.2.72). Licencias y versiones verificadas el 2026-10-31 ([03](../03-reuse-inventory.md)).

## Opciones

| | Harbor | Inspect + inspect_swe |
|---|---|---|
| Agentes integrados | `claude-code`, `codex`, `opencode`, `mini-swe-agent` y ~40 más [Cierto] | `claude_code()`, `codex_cli()`, OpenCode y mini-swe-agent [Cierto] |
| Gateway propio | `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` por agente [Cierto en el código] | `sandbox_agent_bridge()` reenvía al proveedor de Inspect, `litellm_proxy` incluido [Cierto en la documentación]; `claude_code()` rechaza modelos que no son de Anthropic ([#177](https://github.com/meridianlabs-ai/inspect_swe/issues/177)) |
| Formato de tarea | Directorio con `task.toml`, Dockerfile, `tests/test.sh` → reward. Independiente del framework [Cierto] | Tareas en Python (`Task`, `scorer`) |
| Red | `no-network` y `allowlist` con un sidecar nftables, que falla de forma cerrada si el kernel no lo soporta [Cierto, spike 1] | Sandbox Docker de Inspect [Probable] |
| Resultados | `result.json` con tokens, coste, reward y tiempos por fase [Cierto, spike 1]; trayectoria ATIF | Logs `.eval` binarios, auditables con Inspect View [Cierto] |
| Ventaja propia | Tareas como ficheros portables; registro de datasets | Límites uniformes de tokens y tiempo vía el bridge |

## Decisión

**Harbor**, usado solo para la **fase de generación** y para exportar el diff. El veredicto lo da el verificador aislado ([05](../05-verification-design.md)): el verificador de Harbor corre en el mismo host Docker y no cumple la tesis 2.

Motivos:
- El formato de tarea es de ficheros, no de código (tesis 8).
- Los cuatro agentes de F0 vienen integrados con su gateway configurable.
- Falla de forma cerrada con políticas de red que no puede aplicar.

**Condición**: la parte B del spike 1 tiene que confirmar Claude Code a través del gateway (B1, B2, B4). Si falla B1 y no tiene arreglo en ≤ 2 h, se pasa a Inspect. Si falla B3 (Codex con GLM), no se cambia de runner: se aplica el plan B único del brazo A2, OpenHands SDK × GLM ([04](../04-executor-contract.md), decisiones abiertas).

## Consecuencias

- Un conversor OpenSpec → tarea de Harbor (backlog F0-08).
- Las tareas de Harbor que se replican a la torre **no llevan `solution/` ni los tests ocultos**.
- Coste y tokens se toman del gateway, no del `agent_result` de Harbor.
- El diff no se toma del verificador de Harbor: el harness lo calcula en el host ([04](../04-executor-contract.md) §3).

## Cómo revertir

Las tareas viven en OpenSpec en el almacén propio, y los schemas del contrato, el cálculo del diff (en el host), el coste (gateway), el normalizador y el verificador no dependen de Harbor. Lo que sí hay que reescribir son las subclases de agente, el lector de `result.json` y el conversor de tareas. Con Inspect, eso es un `Task` que lea la misma tarea más los agentes de inspect_swe configurados. Estimación: 2–4 días [Suposición].
