# Spike 03 · ¿Basta un juez LLM en vez del verificador?

Pregunta de [ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md): las recetas de Agent Swarm (*litmus tests*, el analista del Ralph loop) usan como puerta de calidad un modelo que lee el resultado y decide. ¿Caza ese juez lo que caza el verificador de la factory con tests ocultos? Si lo cazara casi todo, el verificador aportaría poco.

## Método

- **Datos**: las 502 ejecuciones de la matriz v1 en las que el agente declaró `done`, sin canarias: 346 `accept` y 156 `reject` del verificador.
- **Juez**: recibe el enunciado de la tarea y el diff, sin repositorio ni tests, igual que en las recetas. Aplica una rúbrica de cuatro criterios (`RUBRIC` en `judge_eval.py`) y devuelve `pass` o `fail`.
- **Modelos** de familias distintas de las de los generadores (Claude y GLM):
  - DeepSeek V4 Flash y Qwen 3.8 Flash, a través del gateway, con las 502;
  - Claude Haiku 5.5, que es lo que usa el analista del Ralph loop, por `claude -p` con un turno, sin herramientas, ajustes ni MCP, y solo con los 394 diffs generados con GLM.
- **Métrica principal**: de los cambios que el juez aprueba, qué parte rechaza el verificador. El desglose por motivo del rechazo (diff vacío, diff-guard, tests ocultos) dice qué caza el juez y qué no.

## Cómo se ejecuta

```bash
# en la máquina de la matriz, con el venv de la factory
python spikes/03-llm-judge/judge_eval.py --runs RUNS --store STORE --export prompts.jsonl
python spikes/03-llm-judge/judge_eval.py --prompts prompts.jsonl --model nan/deepseek-v4-flash \
    --out judge-deepseek.jsonl --max-tokens 65536 --workers 6
python spikes/03-llm-judge/judge_eval.py --prompts prompts.jsonl --backend claude-cli \
    --model claude-haiku-5-5 --arms A2,A3,A6 --out judge-haiku.jsonl
```

Los modelos de razonamiento pueden gastar decenas de miles de tokens antes de dar el JSON: con `--max-tokens 16384`, DeepSeek dejó sin veredicto la mitad de los casos. Un 429 de LiteLLM puede ser la clave sin presupuesto, no un límite de peticiones.

## Resultados (2026-11-05)

Sin filtro, el verificador rechaza 156 de las 502 ejecuciones `done` (31 %) [Cierto].

| Juez | Juzgados | Diff vacío cazado | diff-guard cazado | Tests ocultos cazados | Buenos suspendidos | De lo que aprueba, está mal |
|---|---|---|---|---|---|---|
| Claude Haiku 5.5 (solo GLM) | 394 | 34/34 | 12/25 (48 %) | 8/61 (13 %) | 31/274 (11 %) | 66/309 (21 %) |
| DeepSeek V4 Flash | 502 | 34/34 | 20/29 (69 %) | 30/93 (32 %) | 56/346 (16 %) | 72/362 (20 %) |
| Qwen 3.8 Flash | 499 | 34/34 | 19/28 (68 %) | 20/92 (22 %) | 62/345 (18 %) | 81/364 (22 %) |
| Los tres deben aprobar (solo GLM) | 394 | — | — | — | 72/273 (26 %) | 42/243 (17 %) |

- Un juez baja los cambios malos aprobados del 31 % al 20–22 %, pero no los elimina. Lo que se le escapa son los cambios plausibles que no pasan los tests ocultos [Cierto].
- Combinar jueces apenas mejora y suspende más cambios buenos: DeepSeek y Qwen coinciden en 429 de 499 veredictos (86 %) [Cierto].
- Con los diffs de Sonnet (A1), DeepSeek y Qwen aprueban como buenos el 30 % y el 29 % de los cambios malos, frente al 17 % y el 20 % con los de GLM, aunque la tasa de rechazo del verificador es parecida (33 % frente a 30 %) [Cierto]. Que los fallos de un generador mejor parezcan más correctos es una lectura, no está analizado caso a caso [Suposición].
- Tres casos de Qwen quedaron sin veredicto por límites de peticiones del proveedor.

**Decisión**: un juez LLM vale como filtro previo barato (diffs vacíos, trampas visibles, reintentos), no como puerta de fusión. La puerta sigue siendo el verificador con tests ocultos ([ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md)).

## Límites

- El juez no ve el repositorio ni ejecuta nada: es la versión barata, la de las recetas. Un juez agéntico que ejecute tests ya sería un verificador.
- La referencia es el veredicto del verificador, que puede tener falsos rechazos (auditoría F0-19 pendiente).
