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

## Resultados

En curso. Las cifras parciales y el informe están en el almacén privado (`informes/agent-swarm/`).

## Límites

- El juez no ve el repositorio ni ejecuta nada: es la versión barata, la de las recetas. Un juez agéntico que ejecute tests ya sería un verificador.
- La referencia es el veredicto del verificador, que puede tener falsos rechazos (auditoría F0-19 pendiente).
