# CLAUDE.md — mapa del repo

Software factory con agentes de IA: una cadena determinista de ocho etapas (entrada, spec, plan, implementar, verificar, integrar, desplegar y operar) que lleva el trabajo de la intención al producto en producción, para cualquier tipo de software mediante **perfiles** intercambiables. Cada etapa tiene su oráculo y su puerta humana ([ADR-0012](docs/adr/0012-stage-chain-and-profiles.md)). Ejecutores intercambiables (Claude Code, Codex CLI, OpenCode, mini-swe-agent) detrás de un contrato único y de un gateway LiteLLM. El objetivo es L4 *por etapa, tipo de trabajo y perfil*, ganada con datos. Licencia Apache-2.0. Hay código del núcleo (implementar y verificar) en `factory/`; el roadmap va por fases A–D ([docs/07-roadmap.md](docs/07-roadmap.md)).

## Carpetas

| Ruta | Qué es |
|---|---|
| `docs/00-vision.md` … `10-rediseno-propuesta.md` | Diseño. Se leen en orden. Cada documento empieza con un resumen y termina con «Decisiones abiertas». El 10 es la propuesta de rediseño aprobada el 2026-11-02 |
| `docs/adr/NNNN-*.md` | Una decisión por fichero (contexto, opciones, decisión, consecuencias, cómo revertir) |
| `docs/research/` | Investigación de partida. **No se edita**; las correcciones van al 09 §4 |
| `docs/assets/` | Scripts de apoyo a los documentos (p. ej. la simulación de potencia) |
| `schemas/` | JSON Schema 2020-12: contrato de ejecutor (entrada y salida) y evento de trayectoria normalizada |
| `examples/executor/` | Un ejemplo de entrada y salida por adaptador; deben validar contra `schemas/` |
| `spikes/NN-*/` | Experimentos acotados (≤ 2 h) para cerrar un ADR, con un README de resultados |
| `fixtures/` (F0) | Repos de juguete y diffs de trampa por amenaza: los únicos datos de tareas que viven aquí |
| `tasks/*.manifest.json` (F0) | Manifiestos de los conjuntos públicos (dataset de HF, revisión, `instance_id`, digest de imagen). La tarea se regenera a partir de ellos; los tests ocultos nunca están en este repo |
| `factory/` (F0) | Código Python 3.12 (`uv`): `gateway/`, `snapshot/`, `miner/`, `tasks/`, `adapters/`, `verifier/`, `normalize/`, `metrics/` |
| `prompts/` (F0) | Prompts versionados de los ejecutores (`base-v1.md`); cambiar uno dispara M8 |
| `pipelines/` (F1) | Pipelines en YAML validados con `schemas/pipeline.schema.json`; el DOT se genera solo para los diagramas ([ADR-0002](docs/adr/0002-orchestrator.md)) |
| `infra/` (F0) | Scripts del verificador (`verifier/`, con `isolation-check.sh`), sin hosts: los valores van en el almacén privado. La red del sandbox no necesita scripts en la torre: la aplica el modo `allowlist` de Harbor ([02](docs/02-architecture.md) §6) |
| `reports/` (F0) | Informes agregados sin contenido del piloto |
| `.githooks/pre-commit` | Rechaza contenido que coincida con la denylist privada |

## Reglas

1. **Ningún dato del piloto en este repo.** Las tareas, tests ocultos, holdouts, trayectorias, veredictos, nombres de cliente, hosts e IPs internas van en el almacén privado hermano `../factory-pilot-data/` ([ADR-0009](docs/adr/0009-data-policy-per-repo.md)). Activar el hook: `git config core.hooksPath .githooks`. El hook falla de forma cerrada si no encuentra `../factory-pilot-data/denylist.txt`; solo se omite a propósito con `FACTORY_DENYLIST=none`.
2. **Fusible de gasto en cada ejecución.** Todo agente usa una virtual key del gateway con `max_budget`, con un precio sombra mayor que 0 si el proveedor es un plan o un modelo local. Los planes de suscripción se pueden usar (decisión del propietario del 2026-11-01): A1 va con la suscripción de Anthropic y los brazos de GLM con el coding plan de z.ai. La única excepción al gateway es A1 si LiteLLM no puede reenviar el OAuth. En ese caso el fusible lo ponen `--max-budget-usd` y `--max-turns`, y la red se abre solo a la API de Anthropic ([04](docs/04-executor-contract.md) §5.1). Excepción del propietario (2026-11-05): la clave del juez del [spike 03](spikes/03-llm-judge/) va sin `max_budget`, solo con caducidad; no sienta precedente.
3. **El verificador no confía en nada del generador salvo los bytes del diff.** Ningún cambio puede dar al generador acceso a holdouts, tests ocultos, al mirror del verificador ni a su veredicto. La única excepción es la categoría de rechazo de la lista blanca de [05](docs/05-verification-design.md) principio 7, para los reintentos.
4. **Ningún LLM decide el flujo.** Los LLM ejecutan nodos o dan señales blandas que ordenan, nunca convierten un rojo en verde.
5. **Minimalismo verificable.** Un componente nuevo entra con la métrica que mueve o la restricción que cumple en la tabla de [02](docs/02-architecture.md) §7. Si no tiene, no entra.
6. **Versiones fijadas**: CLIs, modelos (alias → modelo inmutable), imágenes por digest. Cambiar una versión crea un brazo nuevo y pasa por M8.
7. **orca-role-hook no tiene licencia**: no se copia código ni prompts suyos. Solo se reimplementan ideas, citando fichero y commit ([ADR-0007](docs/adr/0007-orca-role-hook.md)).
8. **Etiquetas de confianza en `docs/`**: toda afirmación factual, cifra o generalización lleva [Cierto] (fuente primaria enlazada), [Probable] o [Suposición]. Las recomendaciones no llevan etiqueta. Ni el código ni los commits llevan etiquetas.
9. Documentación en español; código, identificadores y mensajes de commit en inglés.
10. **Lo pendiente se pregunta con el formulario de Claude Code** (`AskUserQuestion`), nunca en prosa al final de un mensaje. Vale para dudas, decisiones, preguntas y supuestos por confirmar. La recomendación va primero, marcada «(Recomendado)», y cada pregunta tiene que entenderse sin el texto anterior. Los peones y subagentes no abren formularios: devuelven la duda al orquestador y la pregunta él. Una vez respondida, la decisión se registra en el documento que corresponda (09, un ADR o el roadmap).
11. **Página de estado para el propietario.** El orquestador mantiene un artefacto privado de claude.ai que explica lo hecho y lo pendiente, con el porqué y el para qué de cada punto, las decisiones y los riesgos abiertos. Se actualiza al cerrar cada tarea del backlog, al tomar una decisión o al abrir o cerrar un riesgo. El slug y la fuente HTML viven en `../factory-pilot-data/estado/` (README), no en este repo.
12. **Documentación antes que pruebas, y ninguna prueba porque sí.** Antes de lanzar una prueba, un experimento o una matriz, se consulta la documentación, el código fuente y los datos que ya hay (context7, docs oficiales, ejecuciones anteriores). Una prueba solo entra si responde una pregunta que esas fuentes no resuelven y cuya respuesta cambia una decisión, y se hace en su versión más barata: menos ejecuciones, menos brazos, k=1 si basta. Antes de lanzarla se dicen la pregunta, el coste (tokens y horas de máquina) y la decisión que depende del resultado.

## Quién implementa

- **Peones** (OpenCode con modelos del gateway, en worktrees aislados): las tareas del backlog marcadas «Peón». Reciben la spec de la tarea tal cual, fixtures y, como mucho, la parte visible de las tareas públicas. Nunca datos del almacén privado ni la parte oculta de ninguna tarea.
- **Sonnet** (subagente): verificador antitrampas, contrato de ejecutor, aislamiento y rescates. Como mucho 3 al día, avisando antes.
- **Orquestador** (Claude Code en este repo): configuración, ejecuciones con datos privados, revisión e integración. No escribe la lógica que revisa.
- Un subagente nunca espera más de 270 s entre dos llamadas. Lo que dura más se lanza en segundo plano y se le reanuda cuando hay resultado.

## Cómo se valida

```bash
# Esquemas y ejemplos del contrato
uv run --with check-jsonschema check-jsonschema --check-metaschema schemas/*.json
for n in claude-code codex opencode mini-swe-agent; do
  uv run --with check-jsonschema check-jsonschema --schemafile schemas/executor-input.schema.json  examples/executor/$n.input.json
  uv run --with check-jsonschema check-jsonschema --schemafile schemas/executor-output.schema.json examples/executor/$n.output.json
done
uv run --with jsonschema python -I -c "import json,jsonschema; s=json.load(open('schemas/trajectory-event.schema.json')); [jsonschema.validate(json.loads(l), s) for l in open('examples/executor/trajectory.example.jsonl')]"
# Potencia y margen de no-inferioridad (01-metrics §3)
uv run --with numpy python -I docs/assets/power_sim.py
uv run --with numpy python -I docs/assets/power_sim.py --ni
# Desde F0-01: todo lo anterior y los tests
make check
```

Una tarea del backlog está hecha cuando su **comando de aceptación** termina con exit 0 en un checkout limpio y el orquestador ha revisado el diff. Un cambio en `prompts/`, `pipelines/`, `factory/adapters/`, `factory/verifier/` o en la configuración de modelos necesita además la ejecución de M8 sobre el conjunto congelado ([01](docs/01-metrics.md)). M8 rige desde que F0-18 congela el conjunto v1; antes basta el comando de aceptación.

## Métricas que mandan

M1 coste por cambio aceptado (real + sombra) · M2 pass@1 y pass^k · M3 aceptado sin edición humana · M4 regresiones por cada 100 cambios (SZZ) · M5 trampa en canarias · M6 tiempo hasta PR válido · M7 mantenibilidad · M8 CI de la propia factory. Las definiciones están en [docs/01-metrics.md](docs/01-metrics.md).
