# Spike 03 · ¿Basta un juez LLM en vez del verificador?

Pregunta de [ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md): las recetas de Agent Swarm (*litmus tests*, el analista del Ralph loop) usan como puerta de calidad un modelo que lee el resultado y decide. ¿Caza ese juez lo que caza el verificador de la factory con tests ocultos? Si lo cazara casi todo, el verificador aportaría poco.

## Método

- **Datos**: las ejecuciones de la matriz v1 en las que el agente declaró `done`, sin canarias. Eran 502: 346 `accept` y 156 `reject` del verificador. La auditoría F0-19 descubrió que 16 de ellas eran abortos que el arnés no leía (`.factory/abort.json` iba dentro del diff y el diff-guard lo rechazaba). Una vez reclasificadas, quedan 486, con 140 `reject`.
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

## Resultados (2026-11-05, recalculados el 2026-11-06)

Sin filtro, el verificador rechaza 140 de las 486 ejecuciones `done` (29 %) [Cierto].

| Juez | Juzgados | Diff vacío cazado | diff-guard cazado | Tests ocultos cazados | Buenos suspendidos | De lo que aprueba, está mal |
|---|---|---|---|---|---|---|
| Claude Haiku 5.5 (solo GLM) | 382 | 34/34 | 1/13 (8 %) | 8/61 (13 %) | 31/274 (11 %) | 65/308 (21 %) |
| DeepSeek V4 Flash | 486 | 34/34 | 4/13 (31 %) | 30/93 (32 %) | 56/346 (16 %) | 72/362 (20 %) |
| Qwen 3.8 Flash | 483 | 34/34 | 3/12 (25 %) | 20/92 (22 %) | 62/345 (18 %) | 81/364 (22 %) |
| Los tres deben aprobar (solo GLM) | 379 | — | — | — | 72/273 (26 %) | 42/243 (17 %) |

- Un juez baja los cambios malos aprobados del 29 % al 20–22 %, pero no los elimina. Lo que se le escapa son los cambios plausibles que no pasan los tests ocultos [Cierto].
- **Trampas visibles en el diff: casi no las caza.** La primera versión de esta tabla daba entre el 48 % y el 69 %. Esa cifra estaba inflada por los 16 abortos, cuyo diff llevaba un `abort.json` que cualquier juez ve. Sin ellos, de 12 o 13 rechazos del diff-guard, Haiku caza 1, DeepSeek 4 y Qwen 3 [Cierto]. Esto lo hace el diff-guard, que es determinista y no cuesta nada.
- Combinar jueces apenas mejora y suspende más cambios buenos: DeepSeek y Qwen coinciden en 413 de 483 veredictos (86 %) [Cierto].
- Con los diffs de Sonnet (A1), DeepSeek y Qwen aprueban como buenos cambios que están mal en el 30 % y el 29 % de los casos, frente al 17 % y el 20 % con los de GLM. Mientras tanto, la tasa de rechazo del verificador es parecida (31 % frente a 28 %) [Cierto]. Que los fallos de un generador mejor parezcan más correctos es una lectura mía; no está analizado caso a caso [Suposición].
- Tres casos de Qwen quedaron sin veredicto por límites de peticiones del proveedor.

**Decisión**: un juez LLM vale como filtro previo barato para diffs vacíos y para ordenar reintentos, no como puerta de fusión ni como detector de trampas, que es trabajo del diff-guard. La puerta sigue siendo el verificador con tests ocultos ([ADR-0013](../../docs/adr/0013-verification-layer-over-agent-swarm.md)).

## Límites

- El juez no ve el repositorio ni ejecuta nada: es la versión barata, la de las recetas. Un juez agéntico que ejecute tests ya sería un verificador.
- La referencia es el veredicto del verificador. La auditoría F0-19 da 1 falso `accept` de 30 y 10 de 10 rechazos concordantes [Cierto]. La tabla incluye las seis tareas que la auditoría descartó. Sin ellas, sobre las 26 que se quedan, el verificador rechaza el 20–21 % de lo que el agente da por terminado, y de lo que aprueba el juez queda mal el 12 % con Haiku y el 15 % con DeepSeek o Qwen [Cierto]. Bajan los dos números, pero el juez sigue quitando más o menos un tercio de los cambios malos, y la conclusión es la misma.
