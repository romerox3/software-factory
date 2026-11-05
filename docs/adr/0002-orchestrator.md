# ADR-0002 · Orquestador del pipeline

- **Estado**: sustituida el 2026-11-05 por [ADR-0013](0013-verification-layer-over-agent-swarm.md) (en pausa desde el 2026-11-04); aceptada y revisada el 2026-11-01. El propietario cambia la tesis 8 (sección 4) y el formato pasa de DOT a YAML propio · **Fecha**: 2026-10-31

## Contexto

La tesis 3 pide un pipeline determinista sin LLM supervisor y la tesis 8, pipelines en DOT compatibles con el spec Attractor. F0 no necesita orquestador más allá del runner del harness. F1 necesita un flujo issue → spec → ejecutor → verificador → reintentos → PR en borrador → `needs-human`.

## Opciones

1. **Fork de Tracker** (2389-research, MIT): el motor más completo, con checkpoints, `--max-cost` en céntimos, fan-out a worktrees y puertas humanas [Cierto].
2. **LangGraph (librería, MIT) con NATS**: continuidad con la plataforma del propietario.
3. **Runner propio mínimo** con un formato de grafo, que puede ser:
   - (a) un subconjunto de DOT/Attractor;
   - (b) un subconjunto de Serverless Workflow 1.0 (CNCF);
   - (c) un YAML propio con JSON Schema.

## Datos verificados el 2026-10-31

- **Tracker ha marcado su parser DOT como *deprecated***: «Deprecated: Use .dip format with FromDippinIR instead» (`pipeline/parser.go`). El CHANGELOG 0.69.0 hace de `.dip` la autoridad de los ejemplos [Cierto]. El lenguaje `.dip` ([2389-research/dippin-lang](https://github.com/2389-research/dippin-lang)) **no tiene licencia** [Cierto]. Tiene 2 contribuidores humanos principales [Cierto].
- **El spec Attractor no tiene commits desde el 2026-03-17** [Cierto]. **Kilroy** (la otra implementación DOT) no tiene commits desde el 2026-04-27 [Cierto]. La implementación TypeScript `brynary/attractor` está **archivada** [Cierto].
- Que el flujo de F1 sea **lineal con un bucle de reintento** es juicio propio.
- **Datos del 2026-11-01** (`notas:conocimiento/llm-agentes/formatos-declarativos-para-pipelines-de-agentes.md`):
  - Serverless Workflow es el único estándar vivo con JSON Schema (spec v1.0.3 del 2026-07-31, Apache-2.0, CNCF) [Cierto]. Tiene `try` con reintentos, `switch` y `listen`, pero no `while`, y su SDK de Python no publica release desde 2022 [Cierto].
  - gh-aw no expresa bucles ni ramas [Cierto].
  - No hay ningún estándar de workflows de agentes en la AAIF ni en la LF [Probable].

## Decisión

**Runner propio mínimo** que interpreta un **YAML propio validado con JSON Schema** (`schemas/pipeline.schema.json`, en F1). Decisión del propietario del 2026-11-01, que sustituye al subconjunto de DOT del 2026-10-31.
- **Nodos**: `executor`, `verify`, `condition`, `human_gate` y `exit`, con `max_retries` por nodo.
- **Aristas**: `on: <outcome>` con un conjunto cerrado de valores (`accept`, `reject`, `abort_spec_conflict`, `budget_exceeded`, `error_infra`), y bucles acotados por `max_visits`.
- **Checkpoint** tras cada nodo.
- **DOT generado** a partir del YAML, solo para los diagramas; no es un formato de entrada.

El schema hace el papel del linter del subconjunto. La propuesta es mantener el runner por debajo de ~400 líneas [Suposición].

- LangGraph se descarta para el pipeline: el grafo es lineal, y meter un framework no mueve ninguna métrica (tesis 7). Puede usarse **dentro** de un nodo si algún día un ejecutor lo necesita.
- Tracker queda como **referencia**: con DOT deprecado ya no sirve de plan de salida que comparta formato.
- Serverless Workflow no se adopta: el runner tendría que implementar un subconjunto de un spec pensado para orquestar servicios, y la compatibilidad se quedaría en el nombre, como pasó con Attractor. Queda como **destino de traducción** si algún día hace falta un motor externo.

## Consecuencias

- La complejidad del runner se controla con el schema. Nada de LLM en las aristas.
- Las ejecuciones de pipeline son reproducibles: YAML versionado + `config_sha` + checkpoints en JSONL.
- El pipeline se valida con el mismo `check-jsonschema` que el contrato de ejecutor, en `make check`.

## 4. Tesis 8, revisada

La tesis 8 elegía DOT «compatible con el spec de Attractor» como formato portable entre runners. El 2026-10-31 se vio que el spec está parado, que el motor más completo abandona DOT por un formato sin licencia y que la segunda implementación también está parada [Cierto]. El 2026-11-01 se investigaron las alternativas (sección de datos), y **el propietario eligió un YAML propio con JSON Schema**. La tesis queda así: *formatos propios, versionados y validables con schema antes que plataformas*. La portabilidad se consigue con una traducción, no con un formato compartido.

## Cómo revertir

El YAML es el contrato. Si el runner propio crece por encima de su límite, se escribe un traductor a Serverless Workflow 1.0 y se ejecuta en un motor que lo implemente (por ejemplo, Zigflow sobre Temporal) [Probable: no se ha comprobado la conformidad de ningún motor con 1.0.3]. Volver a DOT es inmediato, porque el diagrama ya se genera desde el YAML.
